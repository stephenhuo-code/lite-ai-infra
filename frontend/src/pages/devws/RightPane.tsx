import { useState } from 'react'
import { FileViewer } from './FileViewer'
import { Terminal } from './Terminal'

type Tab = 'file' | 'term' | 'preview'

export interface RightPaneProps {
  fileName?: string
  fileContent: string
  termLines: string[]
  previewName?: string
  onCollapse: () => void
}

export function RightPane({ fileName, fileContent, termLines, previewName, onCollapse }: RightPaneProps) {
  const [tab, setTab] = useState<Tab>('file')
  const tabBtn = (k: Tab, label: string) => (
    <button onClick={() => setTab(k)} aria-selected={tab === k}
            className={`px-3 py-1.5 rounded-t-lg cursor-pointer ${tab === k ? 'text-[#4F46E5] bg-[#EEF0FF] font-semibold' : 'text-slate-500'}`}>{label}</button>
  )
  return (
    <div className="flex flex-col h-full bg-white">
      <div className="h-10 shrink-0 border-b border-slate-200/70 flex items-center px-2 gap-1 text-[13px]">
        {tabBtn('file', fileName || '文件')}
        {tabBtn('term', '终端')}
        {tabBtn('preview', '数据预览')}
        <button onClick={onCollapse} title="收起" className="ml-auto p-1.5 rounded-lg text-slate-400 hover:text-[#6366F1] hover:bg-slate-50 cursor-pointer">›</button>
      </div>
      <div className="flex-1 min-h-0">
        {tab === 'file' && <FileViewer content={fileContent} />}
        {tab === 'term' && <Terminal lines={termLines} />}
        {tab === 'preview' && (
          <div className="p-4 text-sm text-slate-600">
            {previewName ? <>数据集 <b>{previewName}</b> 预览(采样/列式 = v-next)</> : <span className="text-slate-400">从左树选一个数据集</span>}
          </div>
        )}
      </div>
    </div>
  )
}
