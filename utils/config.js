// 云服务公开配置（由 WorkBuddy Cloud Service 下发，可随小程序代码发布）
// 说明：这里只包含 publishableKey 这类「应用标识」，不含任何服务端密钥。
module.exports = {
  endpoint: 'https://mp-api.app.workbuddy.host',
  publishableKey: 'wbpk_1DqL7yie0h96oSIp5NAuAs_Wk6RjserZV2hLEGS0vq4FLIXkxS3txe6',
  // 数据每天 12:00 由定时任务刷新
  refreshHour: 12,
};
