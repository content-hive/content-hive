| Parse Results |              | 可选 |      |
| ------------- | ------------ | ---- | ---- |
| id            | 主键         |      |      |
| pid           | 唯一标识符   |      |      |
| url           | 解析的URL    |      |      |
| content       | 内容         |      |      |
| media         | 媒体         | ✅    | 可能是多个 |
| author_id     | 作者ID       | ✅    |      |
| platform_id   | 平台ID       |      |      |
| user_id       | 用户ID       | ✅    |      |
| created_time  | 发布时间     | ✅    |      |
| parser        | 使用的解析器 |      |      |
| state         | 状态         |      |      |
| created_at    | 创建时间     |      |      |
| updated_at    | 更新时间     |      |      |



| Author      |              | 可选 |      |
| ----------- | ------------ | ---- | ---- |
| id          | 主键         |      |      |
| platform_id | 平台ID       |      |      |
| uid         | 在平台上的ID |      |      |
| name        | 昵称         | ✅    |      |
| username    | 用户名       |      |      |
| avatar      | 头像链接     | ✅    |      |
| url         | 主页链接     | ✅    |      |
| created_at  | 添加时间     |      |      |
| updated_at  | 更新时间     |      |      |



| Platform   |          | 可选 |      |
| ---------- | -------- | ---- | ---- |
| id         | 主键     |      |      |
| code       | 平台代码 |      |      |
| name       | 名称     |      |      |
| url        | 平台主页 |      |      |
| icon_url   | 图标链接 | ✅    |      |
| created_at | 创建时间 |      |      |
| updated_at | 更新时间 |      |      |



| Media      |          | 可选 |      |
| ---------- | -------- | ---- | ---- |
| id         | 主键     |      |      |
| url        | 媒体地址 |      |      |
| type       | 类型     |      |      |
| title      | 标题     | ✅    |      |
| duration   | 时长     | ✅    |      |
| width      | 宽度     | ✅    |      |
| height     | 高度     | ✅    |      |
| cover      | 视频封面 | ✅    |      |
| media_path | 本地路径 | ✅    |      |
| cover_path | 封面路径 | ✅    |      |
| created_at | 创建时间 |      |      |
| updated_at | 更新时间 |      |      |




| Parse Result Media |                | 可选 | 备注 |
| ------------------ | -------------- | ---- | ---- |
| parse_result_id    | 解析结果ID     |      | 外键 |
| media_id           | 媒体ID         |      | 外键 |
| name     |      |      |
| username |      |      |
|          |      |      |




| Users |          | 可选 |      |
| ------------- | -------- | ---- | ---- |
| id            | 主键     |      |      |
| username      | 用户名   |      |      |
| email         | 邮箱     |      |      |
| password_hash | 密码哈希 |      |      |
| is_active     | 是否激活 |      |      |
| is_admin      | 是否管理员 |      |      |
| created_at    | 创建时间 |      |      |
| updated_at    | 更新时间 |      |      |