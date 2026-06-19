#!/usr/bin/env bash
# spikes/bff_oidc/probe.sh —— Task 1 探查:真 Keycloak OIDC 事实(宪法 §3.4 探查优先)
# 前置:make dev-up(Keycloak :8080 已起,realm-lite-ai 已导)。
# 产出:token 大小 / access TTL / refresh rotation 行为 / cookie 体积 → 人工研判后记进 probe.md。
# 注意:本脚本只观测、不写实现;refresh 策略由实测结论决定(rotation 开→single-flight)。
set -uo pipefail
ISS="http://localhost:8080/realms/lite-ai"
AUTH="$ISS/protocol/openid-connect/auth"
TOKEN="$ISS/protocol/openid-connect/token"
REDIR="http://localhost:8090/auth/callback"

echo "================= 1) ROPC 取 token(gateway 客户端,测大小/TTL/rotation)================="
# gateway 客户端保留 ROPC(集成测试/ops 用);BFF 的 lite-ai-web 无 ROPC,故这里用 gateway。
RESP=$(curl -s -X POST "$TOKEN" \
  -d grant_type=password -d client_id=gateway -d client_secret=dev-secret \
  -d username=alice -d password=alice -d scope=openid)
AT=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
RT=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('refresh_token',''))")
IT=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id_token',''))")
EXPIRES_IN=$(echo "$RESP" | python3 -c "import sys,json;print(json.load(sys.stdin).get('expires_in',''))")
if [ -z "$AT" ]; then echo "ROPC 失败:$RESP"; exit 1; fi
echo "access_token  字节数: ${#AT}"
echo "refresh_token 字节数: ${#RT}"
echo "id_token      字节数: ${#IT}"
echo "expires_in (access TTL 秒): $EXPIRES_IN  →  $((EXPIRES_IN/60)) min"
echo "--- access token claims(groups/exp/iat)---"
echo "$AT" | python3 -c "
import sys,base64,json
t=sys.stdin.read().strip().split('.')[1]
t+='='*(-len(t)%4)
c=json.loads(base64.urlsafe_b64decode(t))
print('  groups:',c.get('groups'))
print('  exp-iat:',c.get('exp',0)-c.get('iat',0),'秒')
print('  iss:',c.get('iss')); print('  aud:',c.get('aud')); print('  azp:',c.get('azp'))
"

echo
echo "================= 2) refresh rotation 行为(同一 refresh token 连刷两次)================="
R1=$(curl -s -X POST "$TOKEN" -d grant_type=refresh_token -d client_id=gateway -d client_secret=dev-secret -d refresh_token="$RT")
RT2=$(echo "$R1" | python3 -c "import sys,json;print(json.load(sys.stdin).get('refresh_token',''))")
ERR1=$(echo "$R1" | python3 -c "import sys,json;print(json.load(sys.stdin).get('error',''))")
echo "第 1 次刷新: error='$ERR1'  新 refresh 与旧相同? $([ "$RT" = "$RT2" ] && echo YES || echo NO)"
# 用【同一旧 RT】再刷一次 —— rotation 开则第二次应被拒(旧 RT 已失效)
R2=$(curl -s -X POST "$TOKEN" -d grant_type=refresh_token -d client_id=gateway -d client_secret=dev-secret -d refresh_token="$RT")
ERR2=$(echo "$R2" | python3 -c "import sys,json;print(json.load(sys.stdin).get('error',''))")
AT2=$(echo "$R2" | python3 -c "import sys,json;print(json.load(sys.stdin).get('access_token',''))")
echo "第 2 次刷新(复用旧 RT): error='$ERR2'  拿到 access? $([ -n "$AT2" ] && echo YES || echo NO)"
echo ">>> 结论:若第2次 error 非空/无 access ⇒ rotation 开(需 single-flight);若仍成功 ⇒ rotation 关(直刷)。"

echo
echo "================= 3) cookie 体积(Fernet 加密 {access,refresh,exp})================="
python3 - "$AT" "$RT" "$EXPIRES_IN" <<'PY'
import sys, json
from cryptography.fernet import Fernet
at, rt, exp = sys.argv[1], sys.argv[2], sys.argv[3]
key = Fernet.generate_key()
f = Fernet(key)
payload = json.dumps({"access_token": at, "refresh_token": rt, "expires_at": 9999999999, "csrf": "x"*43})
ct = f.encrypt(payload.encode()).decode()
print(f"  明文 JSON 字节: {len(payload)}")
print(f"  Fernet 密文(cookie 值)字节: {len(ct)}")
print(f"  + 'session=' 前缀后: {len(ct)+8} (单 cookie 上限 ~4096)")
print(f"  <4KB ? {'YES (方案成立)' if len(ct)+8 < 4096 else 'NO (需降级:只存 refresh / 拆 cookie)'}")
PY

echo
echo "================= 4) PKCE 授权码流(curl 脚本化登录,验证 code+PKCE 端到端)================="
# curl 处理 KC 会话 cookie(AUTH_SESSION_ID/KC_RESTART)更稳;urllib 的 cookiejar 在 KC 表单流上易丢 cookie。
CJ="$(mktemp)"
V=$(python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(40)).rstrip(b'=').decode())")
CH=$(python3 -c "import hashlib,base64,sys;print(base64.urlsafe_b64encode(hashlib.sha256(sys.argv[1].encode()).digest()).rstrip(b'=').decode())" "$V")
HTML=$(curl -s -c "$CJ" -G "$AUTH" \
  --data-urlencode client_id=gateway --data-urlencode response_type=code --data-urlencode scope=openid \
  --data-urlencode redirect_uri="$REDIR" --data-urlencode state=probe-state \
  --data-urlencode code_challenge="$CH" --data-urlencode code_challenge_method=S256)
ACTION=$(echo "$HTML" | grep -oE 'action="[^"]+"' | head -1 | sed 's/action="//;s/"$//;s/\&amp;/\&/g')
LOC=$(curl -s -b "$CJ" -c "$CJ" -o /dev/null -D - \
  --data-urlencode username=alice --data-urlencode password=alice "$ACTION" \
  | grep -i '^location:' | tr -d '\r' | sed 's/[Ll]ocation: //')
CODE=$(echo "$LOC" | grep -oE 'code=[^&]+' | sed 's/code=//')
RSTATE=$(echo "$LOC" | grep -oE '[?&]state=[^&]+' | head -1 | sed 's/.*state=//')
echo "  授权码回调含 code? $([ -n "$CODE" ] && echo YES || echo NO);state 回显匹配? $([ "$RSTATE" = "probe-state" ] && echo YES || echo NO)"
if [ -n "$CODE" ]; then
  curl -s -X POST "$TOKEN" -d grant_type=authorization_code -d client_id=gateway -d client_secret=dev-secret \
    -d code="$CODE" -d redirect_uri="$REDIR" -d code_verifier="$V" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print('  code+PKCE 换 token 成功?', 'YES' if d.get('access_token') else 'NO','; expires_in=',d.get('expires_in'),'; err=',d.get('error'))"
  # 负向:错误 verifier 应被拒(PKCE 生效)。注意 code 已被上面消费,故重跑登录拿新 code 验。
  HTML2=$(curl -s -c "$CJ" -G "$AUTH" --data-urlencode client_id=gateway --data-urlencode response_type=code \
    --data-urlencode scope=openid --data-urlencode redirect_uri="$REDIR" --data-urlencode state=s2 \
    --data-urlencode code_challenge="$CH" --data-urlencode code_challenge_method=S256)
  ACTION2=$(echo "$HTML2" | grep -oE 'action="[^"]+"' | head -1 | sed 's/action="//;s/"$//;s/\&amp;/\&/g')
  LOC2=$(curl -s -b "$CJ" -c "$CJ" -o /dev/null -D - --data-urlencode username=alice --data-urlencode password=alice "$ACTION2" | grep -i '^location:' | tr -d '\r')
  CODE2=$(echo "$LOC2" | grep -oE 'code=[^&]+' | sed 's/code=//')
  BADERR=$(curl -s -X POST "$TOKEN" -d grant_type=authorization_code -d client_id=gateway -d client_secret=dev-secret \
    -d code="$CODE2" -d redirect_uri="$REDIR" -d code_verifier=wrong-verifier \
    | python3 -c "import sys,json;print(json.load(sys.stdin).get('error','(none)'))")
  echo "  错误 verifier 换 token error='$BADERR' → 非空即 PKCE 生效(拒绝)"
fi
rm -f "$CJ"
echo
echo "探查完成。请把上面的事实人工研判后记进 spikes/bff_oidc/probe.md。"
