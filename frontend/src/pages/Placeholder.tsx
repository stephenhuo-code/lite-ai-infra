// 占位页(后续 task 4/5/6 替换为真实内容)。
export function Placeholder({ title }: { title: string }) {
  return (
    <div className="text-slate-500">
      <h1 className="font-semibold text-base text-slate-800 mb-2">{title}</h1>
      <p className="text-sm">此页将在后续迭代实现。</p>
    </div>
  )
}
