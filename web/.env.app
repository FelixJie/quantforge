# 手机 App(Capacitor)构建专用环境变量。
# Web/dev/服务器部署不要用它(那些走相对 /api)。
# 用法:  npm run build:app   (见 package.json,会 --mode app 读取本文件)
# 指向已部署的云端后端。若后端换 IP/上了 HTTPS 域名,改这里即可。
VITE_API_BASE=http://106.12.146.52
