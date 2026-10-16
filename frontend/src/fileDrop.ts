export function listenForFileDrops(target: Window, onDragChange: (active: boolean) => void, onFiles: (files: File[]) => void) {
  const capture = { capture: true }
  let depth = 0
  let active = false
  const isFileDrag = (event: DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes('Files')
  const reset = () => {
    depth = 0
    if (active) onDragChange(false)
    active = false
  }
  const enter = (event: DragEvent) => {
    if (!isFileDrag(event)) return
    event.preventDefault()
    depth++
    if (!active) onDragChange(true)
    active = true
  }
  const over = (event: DragEvent) => {
    if (!isFileDrag(event)) return
    event.preventDefault()
    if (event.dataTransfer) event.dataTransfer.dropEffect = 'copy'
    // Recover when a browser delivers dragover without an initial dragenter.
    if (!active) { depth = 1; active = true; onDragChange(true) }
  }
  const leave = (event: DragEvent) => {
    if (!active) return
    depth = Math.max(0, depth - 1)
    const outside = !event.relatedTarget && (event.clientX <= 0 || event.clientY <= 0
      || event.clientX >= target.innerWidth || event.clientY >= target.innerHeight)
    if (depth === 0 || outside) reset()
  }
  const drop = (event: DragEvent) => {
    if (!active && !isFileDrag(event)) return
    event.preventDefault()
    event.stopPropagation()
    const files = Array.from(event.dataTransfer?.files ?? [])
    reset()
    onFiles(files)
  }
  const visibility = () => { if (target.document.hidden) reset() }
  target.addEventListener('dragenter', enter, capture)
  target.addEventListener('dragover', over, capture)
  target.addEventListener('dragleave', leave, capture)
  target.addEventListener('drop', drop, capture)
  target.addEventListener('dragend', reset, capture)
  target.addEventListener('blur', reset)
  target.document.addEventListener('visibilitychange', visibility)
  return () => {
    target.removeEventListener('dragenter', enter, capture)
    target.removeEventListener('dragover', over, capture)
    target.removeEventListener('dragleave', leave, capture)
    target.removeEventListener('drop', drop, capture)
    target.removeEventListener('dragend', reset, capture)
    target.removeEventListener('blur', reset)
    target.document.removeEventListener('visibilitychange', visibility)
  }
}
