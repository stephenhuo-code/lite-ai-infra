import { useState } from 'react'

// Dev Workspace 左树(plan 9b · US1):工作目录 / 数据目录(catalog)/ Git 三段,可折叠。
// 视觉照高保真原型(brand #6366F1)。数据由父组件经 BFF 反代取(api/devws.ts)。
const BRAND = '#6366F1'

export interface GitChange { x: string; path: string }
export interface DatasetItem { name: string; kind?: string }

export interface LeftTreeProps {
  workingFiles: string[]
  datasets: DatasetItem[]
  gitChanges: GitChange[]
  onSelectDataset: (name: string) => void
}

function Section({ title, hint, children }: { title: string; hint?: string; children: React.ReactNode }) {
  const [open, setOpen] = useState(true)
  return (
    <div className="mb-1">
      <button
        onClick={() => setOpen(o => !o)}
        className="w-full flex items-center gap-1.5 px-1.5 py-1.5 text-[11px] font-semibold text-slate-400 uppercase tracking-wider hover:text-slate-600 cursor-pointer"
      >
        <span style={{ transform: open ? 'rotate(90deg)' : 'none', transition: 'transform .15s' }}>▸</span>
        {title}
        {hint && <span className="ml-auto normal-case tracking-normal text-[10px] text-slate-300">{hint}</span>}
      </button>
      {open && <div className="pl-2">{children}</div>}
    </div>
  )
}

export function LeftTree({ workingFiles, datasets, gitChanges, onSelectDataset }: LeftTreeProps) {
  return (
    <div className="text-sm">
      <Section title="工作目录" hint="~/ws">
        {workingFiles.map(f => (
          <div key={f} className="px-2 py-1.5 rounded-lg hover:bg-slate-50 text-slate-600">{f}</div>
        ))}
      </Section>

      <Section title="数据目录">
        {datasets.map(d => (
          <button
            key={d.name}
            onClick={() => onSelectDataset(d.name)}
            className="w-full text-left px-2 py-1.5 rounded-lg hover:bg-[#EEF0FF] cursor-pointer flex items-center gap-2"
            style={{ color: BRAND }}
          >
            {d.name}
            {d.kind && <span className="ml-auto text-[10px] text-slate-400">{d.kind}</span>}
          </button>
        ))}
      </Section>

      <Section title="Git" hint="main">
        {gitChanges.map(c => (
          <div key={c.path} className="px-2 py-1.5 rounded-lg hover:bg-slate-50 flex items-center gap-2">
            <span className="w-4 text-center text-amber-600 font-bold text-xs">{c.x}</span>
            <span className="text-slate-600">{c.path}</span>
          </div>
        ))}
      </Section>
    </div>
  )
}
