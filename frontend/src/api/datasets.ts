import { api } from './client'
import type { components } from './types-metadata'

// 数据集目录注册/列表 API(catalog-driven · ADR-016/ADR-023)。
// 端点形态以契约 contracts/openapi/metadata.yaml + 生成类型 types-metadata.ts 为准:
//   GET  /v1/catalogs/data/schemas/datasets/datasets → DatasetList { datasets[] }(含 kind/derived_from)
//   POST /v1/catalogs/data/schemas/datasets/datasets ← RegisterDataset
// metadata-service 按企业/组 can() 过滤;raw 注册不带 location(服务端钉死),
// processed 注册由 job 产物给 location + num_samples(只读自 job,FR-010)。
export type Dataset = components['schemas']['Dataset']
export type DatasetList = components['schemas']['DatasetList']
export type RegisterDataset = components['schemas']['RegisterDataset']

const BASE = '/v1/catalogs/data/schemas/datasets/datasets'

// 列数据集(已处理 + raw 都在,带 kind)。
export const listDatasets = (): Promise<DatasetList> => api.get(BASE)

// 注册数据集到目录(raw / processed)→ 返回登记后的 Dataset。
export const registerDataset = (body: RegisterDataset): Promise<Dataset> =>
  api.post(BASE, body)
