import { api } from './client'

// 三段直传(ADR-020):① 经 gateway 申请通行证(不选组——组由身份带出,
// 服务端 can() 后拼 OSS key)→ ② 字节直 PUT presigned OSS URL(非同源,
// 不走同源 client,故用裸 fetch)→ ③ complete 仅带 raw_id(服务端按记录再校验)。
type UploadReq = { dataset: string; filename: string; file: Blob }

export async function uploadDataset(
  r: UploadReq,
  onProgress: (pct: number) => void,
) {
  // ① 申请通行证:经 gateway,不选组。grant 契约见 types-datapipeline UploadGrant。
  const grant = await api.post('/v1/data/raw', { dataset: r.dataset, filename: r.filename })
  onProgress(10)
  // ② 直 PUT OSS(presigned URL,非同源——不带会话 cookie / CSRF)。
  const put = await fetch(grant.url, { method: 'PUT', body: r.file })
  if (!put.ok) throw new Error(`OSS PUT ${put.status}`)
  onProgress(90)
  // ③ complete:入参仅 path raw_id;服务端再 can() + 校验对象。
  const out = await api.post(`/v1/data/raw/${grant.raw_id}/complete`, {})
  onProgress(100)
  return out
}
