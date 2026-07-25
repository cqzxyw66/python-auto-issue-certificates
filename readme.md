## 本项目是基于 Python 开发的证书管理与证书申请工具，支持配置公司信息、LDAP 连接、CA 证书生成、域控证书上传、客户端下载、密码修改、历史记录和日志查看。

### 使用方法

- 安装 Python 3
- 安装依赖：`py -m pip install -r requirements.txt`
- 运行服务：`py app.py`
- 打开浏览器访问：`http://127.0.0.1:5000`

### Docker

- 构建镜像：`docker build -t certificate-manager .`
- 运行容器：`docker run -p 5000:5000 certificate-manager`

### 默认管理员

- 用户名：`admin`
- 密码：`admin123`

首次登录会强制要求修改管理员密码。