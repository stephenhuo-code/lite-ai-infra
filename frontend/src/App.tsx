import { Routes, Route, Navigate } from 'react-router-dom'
import { Shell } from './app/Shell'
import { Account } from './pages/Account'
import { Datasets } from './pages/Datasets'
import { Placeholder } from './pages/Placeholder'

// 路由:Shell 套 6 屏(datasets/catalog/pipelines/create/account)。
// datasets/account 已接真实页;其余屏先占位,Task 5/6 替换。
export default function App() {
  return (
    <Routes>
      <Route element={<Shell />}>
        <Route index element={<Navigate to="/datasets" replace />} />
        <Route path="/datasets" element={<Datasets />} />
        <Route path="/catalog" element={<Placeholder title="数据目录" />} />
        <Route path="/pipelines" element={<Placeholder title="数据管线" />} />
        <Route path="/create" element={<Placeholder title="创建作业" />} />
        <Route path="/account" element={<Account />} />
        <Route path="*" element={<Navigate to="/datasets" replace />} />
      </Route>
    </Routes>
  )
}
