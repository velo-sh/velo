# Velo Benchmark 使用手册

> 从用户角度一步步运行 Velo 性能基准测试

## 📋 目录

1. [前置条件](#-前置条件)
2. [快速开始 (5分钟)](#-快速开始-5分钟)
3. [测试单个框架](#-测试单个框架)
4. [CI/CD 集成](#%EF%B8%8F-cicd-集成)
5. [解读测试结果](#-解读测试结果)
6. [常见问题](#-常见问题)

---

## ✅ 前置条件

### 1. 确保 Velo 已编译

```bash
# 在 velo_qa 根目录
cargo build --release

# 验证编译成功
./target/release/velo --version
```

### 2. 确保 Python 环境

```bash
# 推荐使用 uv
uv sync

# 或者确保已安装 Python 3.11+
python3 --version
```

---

## 🚀 快速开始 (5分钟)

### Step 1: 进入 benchmarks 目录

```bash
cd benchmarks
```

### Step 2: 运行 Hello World 级别测试

```bash
python3 benchmark_framework_scale.py --all --level L1
```

### Step 3: 查看结果

输出示例：
```
==========================================================================================
🎯 FRAMEWORK SCALING BENCHMARK RESULTS
==========================================================================================
Framework    Level Scale           Components   Build (ms)    Load (ms) Status  
------------------------------------------------------------------------------------------
fastapi      L1    Hello World              2         35.1        390.9 ✅ PASS  
flask        L1    Hello World              1         22.2        197.6 ✅ PASS  
django       L1    Hello World              1         22.3        271.6 ✅ PASS  
==========================================================================================
```

### Step 4: 运行完整测试 (所有级别)

```bash
python3 benchmark_framework_scale.py --all
```

⏱️ 预计时间：约 3-5 分钟

---

## 🎯 测试单个框架

### FastAPI

```bash
# 仅 FastAPI，所有级别
python3 benchmark_framework_scale.py --fastapi

# FastAPI L5 企业级 (700 组件)
python3 benchmark_framework_scale.py --fastapi --level L5
```

### Flask

```bash
# 仅 Flask，所有级别
python3 benchmark_framework_scale.py --flask

# Flask L3 中型项目 (50 组件)
python3 benchmark_framework_scale.py --flask --level L3
```

### Django

```bash
# 仅 Django，所有级别
python3 benchmark_framework_scale.py --django

# Django L4 大型项目 (50 apps)
python3 benchmark_framework_scale.py --django --level L4
```

---

## 🏗️ 企业级压力测试

如果需要更真实的生产环境模拟：

```bash
# 运行企业级基准
python3 benchmark_enterprise.py --all

# 单独运行 FastAPI 企业级 (500+ Pydantic 模型)
python3 benchmark_enterprise.py --fastapi
```

---

## ⚙️ CI/CD 集成

### Step 1: 导出 JSON 结果

```bash
python3 benchmark_framework_scale.py --all --output ci_results.json
```

### Step 2: 在 CI 脚本中检查阈值

```bash
# 示例: 检查 L5 build 时间是否超过 150ms
python3 -c "
import json
with open('ci_results.json') as f:
    data = json.load(f)
for r in data['results']:
    if r['level'] == 'L5' and r['build_time_ms'] > 150:
        print(f\"REGRESSION: {r['framework']} build {r['build_time_ms']}ms > 150ms\")
        exit(1)
print('All benchmarks within threshold!')
"
```

### Step 3: GitHub Actions 集成示例

```yaml
- name: Run Performance Benchmarks
  run: |
    cd benchmarks
    python3 benchmark_framework_scale.py --all --output results.json

- name: Check for Regressions
  run: |
    python3 scripts/check_benchmark_thresholds.py results.json
```

---

## 📊 解读测试结果

### 指标说明

| 指标 | 说明 | 目标 |
|:---|:---|:---|
| **Build (ms)** | `velo bundle build` 耗时 | L5 < 150ms |
| **Load (ms)** | `velo run --fast` 启动耗时 | L5 < 800ms |
| **Components** | 生成的组件数量 | - |

### 级别说明

| Level | 场景 | 典型规模 |
|:---:|:---|:---|
| L1 | Hello World | 1-5 组件 |
| L2 | 小型项目 | 10-20 组件 |
| L3 | 中型项目 | 50-100 组件 |
| L4 | 大型项目 | 200-500 组件 |
| L5 | 企业级 | 500-1000+ 组件 |

### 性能基线参考

```
FastAPI L5 (700 组件): Build ~107ms, Load ~567ms
Flask   L5 (200 组件): Build ~56ms,  Load ~284ms
Django  L5 (100 apps): Build ~54ms,  Load ~316ms
```

---

## ❓ 常见问题

### Q: 测试失败显示 "Velo binary not found"

**A:** 确保已编译 Release 版本：
```bash
cd ..  # 回到 velo_qa 根目录
cargo build --release
cd benchmarks
```

### Q: FastAPI 测试报 "pydantic not found"

**A:** 脚本会自动安装依赖，但如果失败，手动安装：
```bash
uv add fastapi pydantic flask django
```

### Q: 测试太慢

**A:** 可以只测试特定级别：
```bash
# 只测 L1 和 L2
python3 benchmark_framework_scale.py --all --level L1
python3 benchmark_framework_scale.py --all --level L2
```

### Q: 如何对比两次测试结果

**A:** 导出 JSON 并对比：
```bash
# 第一次测试
python3 benchmark_framework_scale.py --all --output before.json

# 修改代码后
python3 benchmark_framework_scale.py --all --output after.json

# 对比 (手动或使用脚本)
diff before.json after.json
```

---

## 📎 相关链接

- [性能基线文档](../docs/qa/benchmarks/FRAMEWORK_SCALE_BASELINES.md)
- [主 README](./README.md)
- [QA 测试指南](../docs/qa/tiered-testing-guide.md)

---

**Velo QA Working Group** | Phase 6.0
