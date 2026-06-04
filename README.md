# 行为口令项目

- `app.py`：本地行为口令演示程序
- `behavioral_password_core.py`：行为特征提取、模板建模和验证逻辑
- `作品设计报告-final.pdf`：实验报告

本地运行方式：

```powershell
python app.py
```


说明：

- 首次运行会自动创建 `data/profiles.json`
- 字符口令不明文保存，文件中只保存 PBKDF2-SHA256 带盐哈希和击键行为特征
