import Editor from '@monaco-editor/react'

// 文件查看(plan 9b · Task6):只读 monaco。content 由父组件经 BFF 取(omnigent filesystem)。
export function FileViewer({ content, language = 'python' }: { content: string; language?: string }) {
  return (
    <Editor height="100%" language={language} value={content} theme="vs"
            options={{ readOnly: true, minimap: { enabled: false }, fontSize: 12.5, scrollBeyondLastLine: false }} />
  )
}
