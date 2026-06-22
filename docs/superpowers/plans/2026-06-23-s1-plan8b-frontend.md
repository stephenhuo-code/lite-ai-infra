# Plan 8b — 数据域控制台(React/Vite 前端)Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development(推荐)或 superpowers:executing-plans 逐 task 实现。步骤用 checkbox(`- [ ]`)跟踪。

**Goal:** 把高保真原型 `docs/superpowers/prototypes/2026-06-22-data-domain-hifi.html` 做成**真调 BFF 的数据域控制台**,经 gateway/BFF 调真服务完成数据域核心流(登录 / 数据集 / 上传 / 数据目录 / 数据管线 / 创建作业 / 账户),关闭 S1 出口⑤。

**Architecture:** `frontend/` React+Vite SPA;**同源**——dev 用 vite proxy 把 `/auth /v1` 转 gateway(:8090),prod 由 gateway StaticFiles serve `frontend/dist`。前端零授权、不持 token(凭 BFF HttpOnly 会话 cookie);**唯一非同源例外**:上传字节直 PUT 到 OSS(ADR-020 §5)。前端类型由 `openapi-typescript` 从契约生成。

**Tech Stack:** Vite 8 + React 19 + TS 6 · react-router · Tailwind(Vite 插件)· `fetch` 薄拦截器 · vitest(组件单元)· **Playwright(真浏览器 e2e,会话用 Plan 6 `SessionCodec` browserless 注入)** · openapi-typescript(类型生成)。

**依据:** spec/design `docs/superpowers/plans/2026-06-21-s1-plan8-frontend/{spec.md,design.md}`(已过 DoR);ADR-019(GUI+BFF+serve dist 同源)/ ADR-020(上传 presigned)。前置:Plan 6 BFF ✅、Plan 7 上传 ✅、Plan 8a metadata 3 字段 ✅(均已合并)。探针 A/C 已通(Vite build 出 dist、openapi-typescript 可生成);B/D 作本 plan Task 1/2 当场验。

**范围(spec):** 6 用户故事 US1 登录看数据(P1)/ US2 上传(P2)/ US3 浏览目录(P2)/ US4 提交+跟踪作业(P2)/ US5 排障(P2)/ US6 账户(P3)。**不做(v2/vN+,UI 不出现)**:SQL/另存为 · 删改/取消/重跑/注册/共享 · 下载导出 · 权限策略 Tab · 数据助手 · 模态/标签列 · 血缘 · 一键从数据集发起作业(S2a)。

---

## File Structure(决策锁定)
**新建(`frontend/` 子目录,node 工具链隔离):**
- `frontend/package.json` `vite.config.ts` `tailwind.config.js` `tsconfig.json` `index.html` — 脚手架 + 同源 proxy + Tailwind。
- `frontend/src/api/types.ts` — openapi-typescript 生成(勿手改)。
- `frontend/src/api/client.ts` — `fetch` 封装(同源、CSRF、401→登录)。
- `frontend/src/auth/useMe.ts` — `GET /auth/me` 会话/身份 hook。
- `frontend/src/app/Shell.tsx` `Login redirect` `nav` — 外壳(可折叠侧栏 + 顶栏 + 登出)。
- `frontend/src/pages/{Datasets,UploadModal,Catalog,Pipelines,CreateJob,Account}.tsx` — 6 屏。
- `frontend/src/api/upload.ts` — 上传三段(请求→PUT OSS→complete)。
- `frontend/e2e/{playwright.config.ts,session.ts,core-flow.spec.ts}` — 真浏览器 e2e。
**修改(后端 / 仓库):**
- `services/gateway/static.py`(新)+ `services/gateway/main.py` — serve dist + SPA fallback。
- `Makefile` — `fe-install / fe-types / fe-build / fe-lint / fe-test / fe-e2e` 目标。

---

## Task 1: 前端脚手架 + 同源 vite proxy(探针 B)+ Tailwind + 类型生成

**Files:** Create `frontend/`(scaffold)、`frontend/vite.config.ts`、`frontend/tailwind.config.js`、`frontend/src/index.css`;Modify `Makefile`。

- [ ] **Step 1: 脚手架 + 依赖**

```bash
cd frontend 2>/dev/null || (cd /Users/yanwen/Documents/github/lite-ai-infra && npm create vite@latest frontend -- --template react-ts)
cd /Users/yanwen/Documents/github/lite-ai-infra/frontend
npm install
npm install -D tailwindcss @tailwindcss/vite openapi-typescript
npm install react-router-dom
```
期望:`frontend/` 生成、`npm install` 成功。

- [ ] **Step 2: 写 `frontend/vite.config.ts`(同源 proxy + 构建产物目录)**

```ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  build: { outDir: 'dist' },
  server: {
    port: 5173,
    proxy: {                                   // dev 同源:浏览器视角 /auth /v1 与前端同源,cookie 自动带
      '/auth': { target: 'http://localhost:8090', changeOrigin: false },
      '/v1':   { target: 'http://localhost:8090', changeOrigin: false },
    },
  },
})
```
`frontend/src/index.css` 顶部加 `@import "tailwindcss";`(Tailwind v4 Vite 插件用法)。

- [ ] **Step 3: Makefile 加前端目标**

`Makefile` 末尾追加:
```makefile
fe-install: ; cd frontend && npm install
fe-types:   ; cd frontend && npx openapi-typescript ../contracts/openapi/metadata.yaml -o src/api/types-metadata.ts && npx openapi-typescript ../contracts/openapi/data-pipeline.yaml -o src/api/types-datapipeline.ts && npx openapi-typescript ../contracts/openapi/identity-org.yaml -o src/api/types-identity.ts
fe-build:   ; cd frontend && npm run build
fe-lint:    ; cd frontend && npm run lint
fe-test:    ; cd frontend && npx vitest run
fe-e2e:     ; cd frontend && npx playwright test
```

- [ ] **Step 4: 生成类型 + 构建,确认 dist 产出**

Run: `make fe-types && make fe-build`
Expected: 生成 `frontend/src/api/types-*.ts`;`frontend/dist/`(含 `index.html` + `assets/`)产出,无报错。

- [ ] **Step 5: 探针 B —— dev proxy 同源带会话调通 `/auth/me`**

> 验"前端经 vite proxy 调 `/auth/me` 能带 BFF 会话 cookie 拿到身份"。需 dev BFF 起着。
Run(三终端/后台):`make dev-up` → 起 gateway(BFF):`make run-gateway`(或 `uv run uvicorn services.gateway.main:app --port 8090`)→ `cd frontend && npm run dev`。
然后浏览器开 `http://localhost:5173`(未登录)→ 应 **302/跳到 `/auth/login`**(经 BFF→KC)。登录后回来,开发者工具 Network 里 `/auth/me` 经 5173 同源、**带 cookie、返回 200 + 身份**。
**决策规则(DoR #4-B)**:`/auth/me` 经 proxy 带 cookie 通 → 采纳 vite proxy(预期通)。**期望:通过。**

- [ ] **Step 6: Commit**

```bash
git add frontend/ Makefile
git commit -m "feat(frontend): Vite+React 脚手架 + 同源 proxy(探针B)+ Tailwind + 类型生成 (Plan 8b)"
```

---

## Task 2: gateway serve `dist` + SPA fallback(探针 D)

**Files:** Create `services/gateway/static.py`;Modify `services/gateway/main.py`;Test `tests/gateway/test_static.py`。

- [ ] **Step 1: 写失败测试 `tests/gateway/test_static.py`**

```python
import pathlib
from fastapi.testclient import TestClient
from services.gateway.static import install_static

def _app(tmp_path, monkeypatch):
    from fastapi import FastAPI
    # 造一个假 dist
    dist = tmp_path / "dist"; (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>app</title>")
    (dist / "assets" / "x.js").write_text("console.log(1)")
    app = FastAPI()
    @app.get("/auth/me")
    def me(): return {"user": "u"}
    @app.get("/v1/ping")
    def ping(): return {"ok": True}
    install_static(app, dist_dir=str(dist))
    return TestClient(app)

def test_unknown_route_returns_index_html(tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch)
    r = c.get("/datasets")              # 前端路由,非 API
    assert r.status_code == 200 and "<title>app</title>" in r.text

def test_api_routes_not_swallowed(tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch)
    assert c.get("/auth/me").json() == {"user": "u"}     # /auth 仍达
    assert c.get("/v1/ping").json() == {"ok": True}      # /v1 仍达

def test_asset_served(tmp_path, monkeypatch):
    c = _app(tmp_path, monkeypatch)
    assert c.get("/assets/x.js").status_code == 200
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/gateway/test_static.py -q`
Expected: FAIL（`ModuleNotFoundError: services.gateway.static`）。

- [ ] **Step 3: 实现 `services/gateway/static.py`**

```python
from __future__ import annotations
import os
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

# 不被 SPA fallback 吞的 API 前缀(请求落它们时不回 index.html)
_API_PREFIXES = ("/auth", "/v1", "/docs", "/openapi.json", "/redoc", "/healthz")

def install_static(app: FastAPI, dist_dir: str) -> None:
    """gateway serve 前端 dist:/assets 静态文件 + 其余未知路径回 index.html(SPA history fallback)。
    必须在所有 API 路由 / 反代挂好之后调用(catch-all 最后注册)。API 前缀显式排除,不被吞。"""
    if not os.path.isdir(dist_dir):
        return  # dist 未构建(纯后端/测试场景)→ 不挂,gateway 正常工作
    app.mount("/assets", StaticFiles(directory=os.path.join(dist_dir, "assets")), name="assets")
    index = os.path.join(dist_dir, "index.html")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if ("/" + full_path).startswith(_API_PREFIXES):
            raise HTTPException(status_code=404, detail="not found")  # API 未命中 → 真 404,不回 index
        return FileResponse(index)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/gateway/test_static.py -q`
Expected: PASS（3 项）。

- [ ] **Step 5: 接进 `services/gateway/main.py`(在 install_request_id 之后,最后挂 static)**

`main.py` 末尾 `install_request_id(app)` 之后追加:
```python
from services.gateway.static import install_static
install_static(app, dist_dir=os.environ.get("FRONTEND_DIST", "frontend/dist"))
```

- [ ] **Step 6: 探针 D 真验 + Commit**

Run(dist 已构建 + gateway 起着):`curl -s -o /dev/null -w "%{http_code}\n" localhost:8090/auth/me`(应 401/200,**不是** index)、`curl -s localhost:8090/datasets | grep -o "<title>"`(应回 index)、`curl -s -o /dev/null -w "%{http_code}\n" localhost:8090/v1/data/jobs`(API 仍达)。
```bash
git add services/gateway/static.py services/gateway/main.py tests/gateway/test_static.py
git commit -m "feat(gateway): serve frontend dist + SPA fallback(探针D,不吞 /auth /v1 /docs) (Plan 8b)"
```

---

## Task 3: API 客户端 + 会话/CSRF/401 + 应用外壳 + 登录跳转/登出 + 我的账户(US1 壳 / US6)

**Files:** Create `frontend/src/api/client.ts`、`frontend/src/auth/useMe.ts`、`frontend/src/app/Shell.tsx`、`frontend/src/pages/Account.tsx`、`frontend/src/main.tsx`(路由);Test `frontend/src/api/client.test.ts`、`frontend/src/app/Shell.test.tsx`。

- [ ] **Step 1: 写 API 客户端失败测试 `frontend/src/api/client.test.ts`**

```ts
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { api, csrfFromCookie } from './client'

beforeEach(() => { document.cookie = 'csrf_token=tok123'; vi.restoreAllMocks() })

describe('api client', () => {
  it('GET 同源、带 credentials', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ok:1}), {status:200}))
    await api.get('/v1/data/jobs')
    expect(f).toHaveBeenCalledWith('/v1/data/jobs', expect.objectContaining({ credentials: 'include' }))
  })
  it('变更请求自动带 X-CSRF-Token(取自 cookie)', async () => {
    const f = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', {status:202}))
    await api.post('/v1/data/prepare', { a: 1 })
    const init = f.mock.calls[0][1]!
    expect((init.headers as any)['X-CSRF-Token']).toBe('tok123')
  })
  it('401 → 跳 /auth/login', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('unauth', {status:401}))
    const assign = vi.fn(); Object.defineProperty(window, 'location', { value: { assign, href:'' }, writable:true })
    await expect(api.get('/v1/me/orgs')).rejects.toBeTruthy()
    expect(assign).toHaveBeenCalledWith('/auth/login')
  })
})
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: FAIL（`./client` 不存在)。

- [ ] **Step 3: 实现 `frontend/src/api/client.ts`**

```ts
export function csrfFromCookie(): string {
  return document.cookie.split('; ').find(c => c.startsWith('csrf_token='))?.split('=')[1] ?? ''
}
const MUT = new Set(['POST', 'PUT', 'PATCH', 'DELETE'])
async function req(method: string, path: string, body?: unknown) {
  const headers: Record<string, string> = {}
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  if (MUT.has(method)) headers['X-CSRF-Token'] = csrfFromCookie()
  const res = await fetch(path, { method, credentials: 'include', headers,
    body: body !== undefined ? JSON.stringify(body) : undefined })
  if (res.status === 401) { window.location.assign('/auth/login'); throw new Error('unauthenticated') }
  if (!res.ok) throw new Error(`${res.status}`)
  return res.status === 204 ? null : res.json()
}
export const api = {
  get: (p: string) => req('GET', p),
  post: (p: string, b?: unknown) => req('POST', p, b),
}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd frontend && npx vitest run src/api/client.test.ts`
Expected: PASS（3 项）。

- [ ] **Step 5: `useMe` hook + 外壳 + 账户页 + 路由(组件 + 测试)**

`frontend/src/auth/useMe.ts`:
```ts
import { useEffect, useState } from 'react'
import { api } from '../api/client'
export type Me = { user: string; enterprise_name?: string; memberships: {group_id:string; role:string}[]; csrf?: string }
export function useMe() {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(true)
  useEffect(() => { api.get('/auth/me').then(setMe).catch(()=>{}).finally(()=>setLoading(false)) }, [])
  return { me, loading }
}
```
`frontend/src/app/Shell.tsx`(可折叠侧栏 + 顶栏 + 登出;类名照原型):
```tsx
import { useState } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { api } from '../api/client'
const NAV = [
  { to: '/datasets', label: '数据集' }, { to: '/catalog', label: '数据目录' },
  { to: '/pipelines', label: '数据管线' }, { to: '/create', label: '创建作业' },
  { to: '/account', label: '我的账户' },
]
export function Shell({ enterprise }: { enterprise?: string }) {
  const [collapsed, setCollapsed] = useState(false)
  const logout = async () => { await api.post('/auth/logout'); window.location.assign('/auth/login') }
  return (
    <div className="flex min-h-screen">
      <aside className={`${collapsed ? 'w-16' : 'w-64'} border-r bg-white transition-all`}>
        <button aria-label="折叠" onClick={() => setCollapsed(v => !v)} className="p-3">☰</button>
        <nav className="p-2 space-y-1">{NAV.map(n => (
          <NavLink key={n.to} to={n.to} className={({isActive}) => `block px-3 py-2 rounded-lg ${isActive?'bg-indigo-50 text-indigo-700':'text-slate-600'}`}>
            {collapsed ? n.label[0] : n.label}
          </NavLink>))}</nav>
      </aside>
      <main className="flex-1">
        <header className="h-14 border-b flex items-center px-6 gap-3">
          <span className="ml-auto text-sm text-slate-500">{enterprise}</span>
          <button onClick={logout} className="text-sm text-red-600">登出</button>
        </header>
        <div className="p-6"><Outlet /></div>
      </main>
    </div>
  )
}
```
`frontend/src/pages/Account.tsx`:
```tsx
import { useMe } from '../auth/useMe'
export function Account() {
  const { me, loading } = useMe()
  if (loading) return <div>加载中…</div>
  if (!me) return <div>未登录</div>
  return (
    <dl className="grid grid-cols-2 gap-3 max-w-md text-sm">
      <dt className="text-slate-500">用户</dt><dd>{me.user}</dd>
      <dt className="text-slate-500">企业</dt><dd>{me.enterprise_name ?? '—'}</dd>
      <dt className="text-slate-500">用户组</dt><dd>{me.memberships?.[0]?.group_id ?? '—'}</dd>
      <dt className="text-slate-500">角色</dt><dd>{me.memberships?.[0]?.role ?? '—'}</dd>
    </dl>
  )
}
```
`frontend/src/app/Shell.test.tsx`(折叠 + 登出):
```tsx
import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { Shell } from './Shell'
it('侧栏可折叠', () => {
  render(<MemoryRouter><Shell enterprise="华研科技" /></MemoryRouter>)
  const aside = document.querySelector('aside')!
  expect(aside.className).toContain('w-64')
  fireEvent.click(screen.getByLabelText('折叠'))
  expect(aside.className).toContain('w-16')
})
```
`frontend/src/main.tsx` 配路由(BrowserRouter,Shell 套 6 屏)。装 `npm i -D @testing-library/react @testing-library/jest-dom jsdom` 并在 `vite.config.ts` 加 `test:{environment:'jsdom'}`。

- [ ] **Step 6: 跑组件测试 + Commit**

Run: `cd frontend && npx vitest run`
Expected: PASS(client + Shell)。
```bash
git add frontend/ && git commit -m "feat(frontend): API 客户端(CSRF/401)+ 可折叠外壳 + 登录跳转/登出 + 账户 (US1壳/US6) (Plan 8b)"
```

---

## Task 4: 数据集页(列表 + 搜索)+ 上传弹窗(Plan 7 三段)(US1 数据集 / US2)

**Files:** Create `frontend/src/api/upload.ts`、`frontend/src/pages/Datasets.tsx`、`frontend/src/pages/UploadModal.tsx`;Test `frontend/src/api/upload.test.ts`、`frontend/src/pages/Datasets.test.tsx`。

- [ ] **Step 1: 上传三段失败测试 `frontend/src/api/upload.test.ts`**

```ts
import { describe, it, expect, vi } from 'vitest'
import { uploadDataset } from './upload'
it('走 请求上传→PUT OSS(直连,非同源)→complete 三段', async () => {
  const calls: string[] = []
  vi.spyOn(globalThis, 'fetch').mockImplementation(async (url: any, init: any) => {
    calls.push(`${init?.method ?? 'GET'} ${url}`)
    if (String(url) === '/v1/data/raw') return new Response(JSON.stringify({raw_id:'raw-1', url:'https://oss.test/k?sig', oss_key:'e/g/raw/x'}), {status:200})
    if (String(url).startsWith('https://oss.test')) return new Response('', {status:200})       // 直传 OSS
    if (String(url) === '/v1/data/raw/raw-1/complete') return new Response(JSON.stringify({status:'ready'}), {status:200})
    return new Response('', {status:404})
  })
  const out = await uploadDataset({ dataset:'cc3m', filename:'a.bin', file: new Blob(['x']) }, ()=>{})
  expect(out.status).toBe('ready')
  expect(calls).toEqual(['POST /v1/data/raw', 'PUT https://oss.test/k?sig', 'POST /v1/data/raw/raw-1/complete'])
})
```

- [ ] **Step 2: 跑确认失败** → Run `cd frontend && npx vitest run src/api/upload.test.ts` → FAIL(`./upload` 无)。

- [ ] **Step 3: 实现 `frontend/src/api/upload.ts`**

```ts
import { api, csrfFromCookie } from './client'
type UploadReq = { dataset: string; filename: string; file: Blob }
export async function uploadDataset(r: UploadReq, onProgress: (pct: number) => void) {
  // ① 请求上传(经 gateway,can()+审计;不选组——组由身份带出)
  const grant = await api.post('/v1/data/raw', { dataset: r.dataset, filename: r.filename })
  onProgress(10)
  // ② 字节直 PUT 到 OSS(非同源,ADR-020 §5;presigned URL 自带签名)
  const put = await fetch(grant.url, { method: 'PUT', body: r.file })
  if (!put.ok) throw new Error(`OSS PUT ${put.status}`)
  onProgress(90)
  // ③ 完成(仅传 raw_id;后端校验对象 + 标 ready)
  const out = await api.post(`/v1/data/raw/${grant.raw_id}/complete`, {})
  onProgress(100)
  return out
}
```
(大文件分片:本轮单 PUT;multipart 走 grant.part_urls,作 FR-008 增强,若 grant 返回 part_urls 则逐片 PUT——留实现期按 grant 形态分支。)

- [ ] **Step 4: 跑确认通过** → PASS。

- [ ] **Step 5: 数据集页 + 上传弹窗(组件 + 测试)**

`frontend/src/pages/Datasets.tsx`:列表合并 metadata `GET /v1/catalogs/data/schemas/datasets/datasets` + Plan7 `GET /v1/data/raw`;列 = 名称/描述/格式/样本数/大小/创建人/操作(详情);搜索按名称过滤;右上"上传数据集"开 `UploadModal`。**不渲染模态/标签列、不出现用户组**(spec FR-012/组织模型)。`UploadModal` 用 `uploadDataset` + 进度条 + 失败重试。
`frontend/src/pages/Datasets.test.tsx`(用 msw 或 mock api):mock 列表返回两条 → 断言渲染名称/格式/样本数列、搜索过滤、缺值(num_samples=null)显示占位"—"不报错(FR-008)。

- [ ] **Step 6: Commit** → `git add frontend/ && git commit -m "feat(frontend): 数据集页(列表+搜索)+ 上传弹窗三段直传 (US1/US2) (Plan 8b)"`

---

## Task 5: 数据目录 Catalog Explorer 两栏(树 + 详情)(US3)

**Files:** Create `frontend/src/pages/Catalog.tsx`、`frontend/src/api/catalog.ts`;Test `frontend/src/pages/Catalog.test.tsx`。

- [ ] **Step 1: 失败测试** `frontend/src/pages/Catalog.test.tsx`:mock `GET /v1/catalogs`→`["data"]`、`/v1/catalogs/data/schemas`→`["datasets"]`、`.../datasets`→两条 → 断言:左树渲染 企业/catalog/schema 三层、可展开折叠;点 schema → 右侧列出数据集(名/owner/格式/注册时间/scope);Tab 仅 概览/详情。

- [ ] **Step 2: 跑确认失败。**

- [ ] **Step 3: 实现 `frontend/src/api/catalog.ts`**(`listCatalogs/listSchemas/listDatasets` 调对应端点)+ `Catalog.tsx`(左 `<aside>` 树:`企业(metalake)→catalog→schema→数据集`,折叠按钮;右详情:面包屑 + schema 标题 + 概览表 + "关于此 Schema";**层级标签对用户显示为 企业→catalog→schema→数据集**,对齐契约路径)。类名照原型 Catalog Explorer 段。**不做权限/策略 Tab、共享/注册/新建/加标签按钮**(spec Out)。

- [ ] **Step 4: 跑确认通过。**

- [ ] **Step 5: Commit** → `git add frontend/ && git commit -m "feat(frontend): 数据目录 Catalog Explorer 两栏(树+详情) (US3) (Plan 8b)"`

---

## Task 6: 数据管线(列表+轮询+失败筛选/详情)+ 创建作业(US4/US5)

**Files:** Create `frontend/src/pages/Pipelines.tsx`、`frontend/src/pages/CreateJob.tsx`、`frontend/src/api/jobs.ts`;Test `frontend/src/api/jobs.test.ts`、`frontend/src/pages/Pipelines.test.tsx`。

- [ ] **Step 1: 轮询失败测试 `frontend/src/api/jobs.test.ts`**

```ts
import { describe, it, expect, vi } from 'vitest'
import { pollJob } from './jobs'
it('按 terminal 轮询到终态(非状态串匹配)', async () => {
  const seq = [{terminal:false,status:'running'},{terminal:false,status:'running'},{terminal:true,status:'succeeded'}]
  let i = 0
  vi.spyOn(globalThis,'fetch').mockImplementation(async () => new Response(JSON.stringify(seq[i++]), {status:200}))
  const final = await pollJob('job-1', { intervalMs: 1 })
  expect(final.terminal).toBe(true); expect(final.status).toBe('succeeded')
})
```

- [ ] **Step 2: 跑确认失败。**

- [ ] **Step 3: 实现 `frontend/src/api/jobs.ts`**

```ts
import { api } from './client'
export async function listJobs(status?: string) {
  return api.get('/v1/data/jobs' + (status ? `?status=${status}` : ''))
}
export async function createJob(body: { dataset: string; group_id: string; tar_dir: string; np?: number; process?: unknown[] }) {
  return api.post('/v1/data/prepare', body)              // S1 源=tar_dir(运维预置;raw→prepare=S2a)
}
export async function pollJob(id: string, opts: { intervalMs?: number } = {}) {
  const wait = opts.intervalMs ?? 2000
  for (;;) {
    const j = await api.get(`/v1/data/jobs/${id}`)
    if (j.terminal) return j                              // 按 terminal 判终态(FR-007)
    await new Promise(r => setTimeout(r, wait))
  }
}
```

- [ ] **Step 4: 跑确认通过。**

- [ ] **Step 5: 数据管线页 + 创建作业页(组件 + 测试)**
`Pipelines.tsx`:作业表(ID/数据集/状态徽章/行数/创建)+ 状态筛选(全部/运行中/已完成/**失败**)+ 行点开详情(用 `pollJob` 轮询运行中、终态展示产物 URI / `error`);**失败筛选 + 详情看失败原因 = US5**。`CreateJob.tsx`:表单(源=数据位置 `tar_dir`、产出名、并行度、算子)→ `createJob` → toast 202 → 跳数据管线。`Pipelines.test.tsx`:mock 列表含一条 failed → 按"失败"筛选只剩它 → 详情显示 error 文本(US5 可证伪)。

- [ ] **Step 6: Commit** → `git add frontend/ && git commit -m "feat(frontend): 数据管线(轮询+失败排障)+ 创建作业 (US4/US5) (Plan 8b)"`

---

## Task 7: Playwright 真浏览器 e2e(真 BFF)+ 手动验收 runbook

**Files:** Create `frontend/e2e/{playwright.config.ts,session.ts,core-flow.spec.ts}`、`frontend/scripts/mint-session.py`;Modify Makefile(`fe-e2e` 已加)。

- [x] **Step 1: 会话注入脚本 `frontend/scripts/mint-session.py`(复用 Plan 6 SessionCodec,browserless 造 cookie)**

```python
"""browserless 造 BFF 会话 cookie,供 Playwright 注入(复用 Plan 6 SessionCodec,免在浏览器走 OIDC)。
打印 JSON {session, csrf} 到 stdout。env:KC/CLIENT/USER/PASS/BFF_SESSION_KEY 同 dev。"""
import json, os, sys, time, httpx
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from services.gateway.bff.session import SESSION_COOKIE, SessionCodec, SessionData
KC = os.environ.get("KC", "http://localhost:8080/realms/lite-ai")
tok = httpx.post(f"{KC}/protocol/openid-connect/token", timeout=15, data={
    "client_id": "gateway", "client_secret": os.environ.get("KC_SECRET","dev-secret"),
    "username": os.environ.get("KC_USER","alice"), "password": os.environ.get("KC_PASS","alice"),
    "grant_type": "password"}).raise_for_status().json()["access_token"]
sd = SessionData(tok, None, int(time.time())+300, csrf="csrf-e2e")
key = os.environ["BFF_SESSION_KEY"].encode()
print(json.dumps({"cookie": SESSION_COOKIE, "session": SessionCodec(key).encode(sd), "csrf": "csrf-e2e"}))
```

- [x] **Step 2: Playwright 配置 + 会话注入 `frontend/e2e/session.ts`**(注:config 落在 `frontend/playwright.config.ts`,testDir `e2e`)

```ts
import { execSync } from 'node:child_process'
export function mintSession() {
  const out = execSync('uv run python frontend/scripts/mint-session.py', { cwd: '../..' , encoding: 'utf8' })
  return JSON.parse(out) as { cookie: string; session: string; csrf: string }
}
```
`frontend/e2e/playwright.config.ts`:baseURL `http://localhost:8090`(gateway serve dist,同源真拓扑),webServer 可选。

- [x] **Step 3: 核心流 e2e `frontend/e2e/core-flow.spec.ts`**(断言改用 role/唯一文案避 strict-mode 多匹配)

```ts
import { test, expect } from '@playwright/test'
import { mintSession } from './session'
test('数据域核心流:注入会话→看数据集→数据目录→数据管线→账户→登出', async ({ context, page }) => {
  const s = mintSession()
  await context.addCookies([
    { name: s.cookie, value: s.session, domain: 'localhost', path: '/' },
    { name: 'csrf_token', value: s.csrf, domain: 'localhost', path: '/' },
  ])
  await page.goto('http://localhost:8090/datasets')
  await expect(page.getByText('数据集')).toBeVisible()           // US1:登录态看到数据集页
  await page.getByRole('link', { name: '数据目录' }).click()
  await expect(page.getByText('Catalog', { exact: false })).toBeVisible()  // US3
  await page.getByRole('link', { name: '数据管线' }).click()
  await expect(page).toHaveURL(/pipelines/)                       // US4/US5
  await page.getByRole('link', { name: '我的账户' }).click()
  await expect(page.getByText('用户组', { exact: false })).toBeVisible()    // US6
})
```

- [x] **Step 4: 跑 e2e(真 BFF + serve dist)** —— 活体跑通:真 Chromium + 真 KC token 注入 → `1 passed`

Run:`make dev-up` → `make fe-build`(出 dist)→ 起 gateway `make run-gateway`(serve dist,:8090)→ `cd frontend && npx playwright install --with-deps chromium && make fe-e2e`(从仓库根 `make fe-e2e`)。
Expected: 核心流 spec PASS(真浏览器、真 BFF 会话、经 gateway 同源调真服务)。

- [x] **Step 5: 全绿门禁 + 手动验收 runbook(owner 可读,step-by-step;宪法 §3.4/ADR-015)**

Run: `make fe-types && make fe-build && make fe-lint && make fe-test && uv run pytest -q`(前端构建/lint/单元 + 后端 static 测试全绿)。

#### 手动验收 runbook(照着一步步跑;这是**有界面**的 plan,你能亲自点)

> 验的是:登录后能在浏览器里点着用数据域(看数据集/目录、上传、建作业跟踪、看账户)。
> 每步一条命令 + “该看到什么”大白话。前置:Docker 已起。

**第 1 步 · 起依赖(MinIO/Keycloak/Gravitino)**
```bash
make dev-up
```
**该看到**:`docker compose ... Started`,无报错。`docker ps` 能看到 keycloak / minio / gravitino 容器在跑。

**第 2 步 · 起后端三服务(identity / metadata / data-pipeline)**
```bash
make up        # 一键起依赖容器 + 全部服务进程(含 :8001/:8002/:8003);已起过可跳
```
**该看到**:`scripts/dev_services.sh up` 把三服务拉起;`make ps` 三个都 RUNNING。

**第 3 步 · 前端构建出 dist**
```bash
make fe-build
```
**该看到**:末尾 `✓ built in ...`,生成 `frontend/dist/index.html`、`frontend/dist/assets/*`。

**第 4 步 · 起 gateway / BFF(serve dist,:8090)**
```bash
make run-gateway      # 从仓库根跑;默认 FRONTEND_DIST=frontend/dist,同源 serve 前端 + 反代下游
```
**该看到**:uvicorn `Application startup complete`,监听 `:8090`。浏览器开 `http://localhost:8090/datasets` 不是 404(出页面或被带去登录)。

**第 5 步 · 登录(US1)**:浏览器开 `http://localhost:8090/datasets`。
**该看到**:未登录被带到 Keycloak 登录页;用 dev 账号 **alice / alice** 登录后回到控制台,左侧出现侧栏(数据集 / 数据目录 / 数据管线 / 创建作业 / 我的账户),右上角有「登出」按钮。
> 注:顶栏**不显示企业名**(后端无 enterprise_name 字段,前端诚实不假装——见 Shell.tsx 注释)。

**第 6 步 · 看数据集 + 上传(US1/US2)**:左栏点「数据集」→ 看列表;点「上传数据集」按钮 → 选个小文件 → 看进度 → 完成。
**该看到**:列表只含你有权的数据(名称 / 格式 / 样本数 / 大小 / 创建人,缺的显 “—”);上传完该数据集出现在列表。

**第 7 步 · 数据目录(US3)**:左栏点「数据目录」→ 展开左侧树 → 点一个 schema。
**该看到**:树能展开 / 折叠(企业 → catalog → schema → 数据集);右侧出该 schema 下的数据资产 + 概览。

**第 8 步 · 建作业 + 跟踪 / 排障(US4/US5)**:点「创建作业」填表提交 → 自动跳「数据管线」看它跑;再按「失败」筛选看失败作业详情。
**该看到**:提交后作业出现在列表,状态自动变到终态(不用手刷);失败的能筛出来、详情有失败原因。

**第 9 步 · 账户 + 登出(US6/US1)**:点「我的账户」看身份;点右上「登出」。
**该看到**:显示用户 / 角色 / 用户组(企业·组显示名诚实占位 “待后端补充”,**无 e-/g- 内部 ID**);点登出后回到未登录态(再开 /datasets 又被带去登录页)。

**第 10 步(可选)· 自动化 e2e 复跑(真浏览器 + 真 BFF,免手点)**
```bash
# 上面第 1~4 步的栈还活着即可。装浏览器(只需一次)后跑:
cd frontend && npx playwright install chromium && make -C .. fe-e2e
```
**该看到**:`1 passed` —— Playwright 真 Chromium 注入 browserless 会话(`scripts/mint-session.py` 用真 KC token + Plan6 `SessionCodec` 造 cookie),走 数据集 → 数据目录 → 数据管线 → 我的账户 全绿。
> gateway 没设 `FRONTEND_DIST` 时(只跑 BFF 不 serve dist)e2e 会因 /datasets 404 失败;`make run-gateway` 默认已带 dist。也可 `E2E_BASE_URL=http://localhost:<port>` 指向另一端口的 dist-serving gateway。

**一句话验收**:浏览器里能登录、点着走完 数据集 / 上传 / 目录 / 作业 / 账户(或 `make fe-e2e` 一把过)→ **出口⑤ 通过**。

- [x] **Step 6: Commit** → `git add -A && git commit -m "test(frontend): Playwright 真浏览器 e2e + 全绿门禁 + owner runbook + 清死文件 (出口⑤) (Plan 8b Task7)"`

---

## Self-Review
- **Spec 覆盖**:US1→Task3(壳/登录)+Task4(数据集);US2→Task4(上传三段);US3→Task5;US4→Task6(建作业+轮询);US5→Task6(失败筛选/详情);US6→Task3(账户)。出口⑤→Task7 e2e + runbook。B/D→Task1/2 当场验。FR-003 不选组→upload.ts 不传 group;FR-004 无内部 ID→Account 只显 group_id 业务字段(注:e2e/runbook 校"无 e-/g-");FR-008 缺值占位→Datasets 测试;FR-012 v2 不出现→各页明确不做。
- **占位符扫描**:基建/客户端/上传/轮询/serve-dist/e2e 均给完整代码;屏组件给数据层+关键结构+测试,**视觉 markup 以原型为源**(Task 各步注明"类名照原型 X 段")——非占位,是"实现照已确认原型"。
- **类型一致性**:`api.get/post`(client.ts)贯穿各 api 模块;`uploadDataset({dataset,filename,file})`、`pollJob(id,{intervalMs})`、`createJob({dataset,group_id,tar_dir,...})` 签名在定义处与调用处一致;会话 cookie 名 `SESSION_COOKIE` 复用 Plan 6,e2e 注入与 BFF 解析对称。
