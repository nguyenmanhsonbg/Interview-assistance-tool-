export function requiredText(value, label) {
  if (typeof value !== "string" || !value.trim()) return `${label} là bắt buộc`;
  return null;
}
