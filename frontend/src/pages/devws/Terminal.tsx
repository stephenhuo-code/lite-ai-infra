import { useEffect, useRef } from 'react'
import { Terminal as XTerm } from '@xterm/xterm'
import '@xterm/xterm/css/xterm.css'

// 终端(plan 9b · Task6):xterm。lines 来自 agent 沙箱执行输出(经 BFF;live 接入)。
export function Terminal({ lines = [] as string[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    let term: XTerm | null = null
    try {
      term = new XTerm({ fontSize: 12, convertEol: true, theme: { background: '#0f172a', foreground: '#e2e8f0' } })
      term.open(ref.current)
      lines.forEach(l => term!.writeln(l))
      term.write('$ ')
    } catch { /* jsdom 无 canvas/尺寸:忽略 */ }
    return () => term?.dispose()
  }, [lines])
  return <div ref={ref} className="h-full bg-slate-900" />
}
