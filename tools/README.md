# 本地工具目录

此目录存放本项目自己的第三方工具副本。用 `scripts/provision_local_tools.ps1` 从本机现有安装复制，不下载新版本，不删除原目录。部署清单在 `manifest.local.json`，不进入 Git。

| 目录 | 用途 |
| --- | --- |
| worldmonitor | 新闻接口、信源目录、全球地图底图 |
| RSSHub | 按需启动的 RSS 聚合服务，含已构建产物和依赖 |
| AIHOT | 本地 AI 热点聚合服务，包含已有的本地适配 |
| opencodex | 已安装的 OpenCodex 软件包副本；账号配置仍在原位置 |
| postgresql/18.6/pgsql | 已安装的 PostgreSQL 和 pgvector 二进制副本 |

Node.js、Python 和 Chrome 仍使用本机安装。登录数据、密钥和生成记录不是代码，不应放进这些第三方仓库。服务默认端口不变，使用同一份数据的服务不要同时启动两次。
