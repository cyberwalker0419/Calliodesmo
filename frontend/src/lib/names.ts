// 名称规范化与匹配工具。
// 背景：后端图谱返回实体的“规范名”（如 Anduril / 10th Mountain Division），
// 而档案卡列表与左侧勾选使用小写名（anduril / 10th mountain division）。
// 因此所有“种子 / 图节点 / 选中项”之间的匹配都必须忽略大小写，统一用 normName 作键。

/** 规范化名称：去首尾空白并转小写，作为大小写无关的匹配键。 */
export function normName(s: string): string {
  return s.trim().toLowerCase();
}

/** 数组中是否包含某名称（大小写无关）。 */
export function hasName(arr: readonly string[], name: string): boolean {
  const key = normName(name);
  return arr.some((x) => normName(x) === key);
}
