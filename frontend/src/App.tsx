import { Routes, Route, Navigate } from 'react-router-dom'
import { Shell } from './app/Shell'
import { Account } from './pages/Account'
import { Catalog } from './pages/Catalog'
import { CreateJob } from './pages/CreateJob'
import { Datasets } from './pages/Datasets'
import { Pipelines } from './pages/Pipelines'
import { Workspace } from './pages/Workspace'

// 路由:Shell 套 7 屏(datasets/catalog/pipelines/create/workspace/account)。全部接真实页。
export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/datasets" replace />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/catalog" element={<Catalog />} />
        <Route path="/pipelines" element={<Pipelines />} />
        <Route path="/create" element={<CreateJob />} />
        <Route path="/workspace" element={<Workspace />} />
        <Route path="/account" element={<Account />} />
        <Route path="*" element={<Navigate to="/datasets" replace />} />
      </Route>
    </Routes>
  )
}
