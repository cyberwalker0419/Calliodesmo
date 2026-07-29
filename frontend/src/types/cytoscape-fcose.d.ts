// cytoscape-fcose 未随包发布类型声明（运行时为 UMD 注册函数），此处补最小声明。
// 真实导出 = register(cytoscape)：向 cytoscape 注册 'fcose' 布局，签名与 cytoscape.Ext 兼容。
declare module "cytoscape-fcose" {
  const fcose: (cy: unknown) => void;
  export default fcose;
}
