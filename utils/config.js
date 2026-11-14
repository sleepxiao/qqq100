// 微信云开发配置
//
// envId 在小程序后台「云开发」控制台首页可以查到，形如 nasdaq100-1g2h3j4k。
// 这个值会随小程序代码一起发布，属于公开标识，不含任何密钥。
module.exports = {
  envId: 'REPLACE_WITH_YOUR_CLOUD_ENV_ID',
  // 数据每天由 GitHub Actions 在北京时间 11:40 抓取并写入，这里只用于界面提示
  refreshHour: 11,
};
