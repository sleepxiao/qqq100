// 数据通道配置
//
// mode = 'static' 读静态托管 JSON（当前方案，不用数据库）
// mode = 'cloud'  读微信云开发文档型数据库（需要环境已转换绑定小程序）
//
// staticBase 是静态托管默认域名，会随小程序代码一起发布，属于公开标识。
module.exports = {
  mode: 'static',
  envId: 'civic-pigeon-d1gc0cqcudc2ccfe0',
  staticBase: 'https://civic-pigeon-d1gc0cqcudc2ccfe0-1532560557.tcloudbaseapp.com',
  // 数据每天由 GitHub Actions 在北京时间 11:40 抓取并写入，这里只用于界面提示
  refreshHour: 11,
};
