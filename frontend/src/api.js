const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:8000'

export async function uploadAudit(file, ruleSetId = 'default') {
  const formData = new FormData()
  formData.append('file', file)
  formData.append('rule_set_id', ruleSetId)

  const response = await fetch(`${API_BASE}/api/v1/audit/upload`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(await response.text())
  }

  return response.json()
}

export async function compareFiles(baseFile, currentFile) {
  const formData = new FormData()
  formData.append('base_file', baseFile)
  formData.append('current_file', currentFile)

  const response = await fetch(`${API_BASE}/api/v1/compare/files`, {
    method: 'POST',
    body: formData,
  })

  if (!response.ok) {
    throw new Error(await response.text())
  }

  return response.json()
}
