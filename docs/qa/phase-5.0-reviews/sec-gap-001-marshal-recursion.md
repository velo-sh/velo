# Phase 5.0 Fast Loader: 安全漏洞报告

> **日期**: 2026-01-03  
> **严重程度**: P0 CRITICAL  
> **状态**: ⚠️ 待修复

---

## 1. 漏洞概述

### SEC-GAP-001: Marshal 递归深度限制未实现

| 字段 | 值 |
|------|---|
| RFC 要求 | §3.5 AUDIT-012 |
| 实现状态 | ❌ 未实现 |
| 影响 | Stack Overflow DoS |
| 攻击难度 | 低 (恶意构造的 .veloc 文件) |

---

## 2. 技术分析

### RFC-0006 §3.5 要求

```python
# RFC 指定的安全实现
MARSHAL_RECURSION_LIMIT = 1000

def safe_marshal_loads(data: bytes) -> object:
    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(MARSHAL_RECURSION_LIMIT)
        return marshal.loads(data)
    finally:
        sys.setrecursionlimit(old_limit)
```

### 当前实现 (velo_loader.py:281)

```python
# 当前: 直接调用,无保护!
code = marshal.loads(code_data)  # ← VULNERABILITY
```

---

## 3. 测试覆盖缺陷

### 现有测试 (test_l4_security.py:402)

```python
def test_deeply_nested_code_handled(self, tmp_path, velo_binary):
    # 只创建 50 层嵌套
    for i in range(50):
        nested = f"(lambda: {nested})()"
    
    # 只检查不 segfault, 不验证限制是否生效
    assert result.returncode != -11  # ← 不够!
```

### 测试缺陷

1. 50 层嵌套太浅,不会触发 stack overflow
2. 不验证 `MARSHAL_RECURSION_LIMIT` 常量
3. 不验证 `safe_marshal_loads` 函数存在
4. 不验证超限时返回正确错误码

---

## 4. 攻击向量

攻击者可构造恶意 `.veloc` 文件:

```
1. 构造深度嵌套的 marshal 数据 (>1000 层)
2. 替换正常 bundle 中的模块数据
3. 用户执行 velo run --fast
4. marshal.loads() 触发无限递归
5. Stack Overflow → Crash
```

---

## 5. 修复方案

### 代码修复 (velo_loader.py)

```python
# 添加常量
MARSHAL_RECURSION_LIMIT = 1000

# 添加安全函数
def safe_marshal_loads(data: bytes) -> object:
    import sys
    old_limit = sys.getrecursionlimit()
    try:
        sys.setrecursionlimit(MARSHAL_RECURSION_LIMIT)
        return marshal.loads(data)
    finally:
        sys.setrecursionlimit(old_limit)

# 修改 exec_module 方法
def exec_module(self, module) -> None:
    ...
    # code = marshal.loads(code_data)  # 旧代码
    code = safe_marshal_loads(code_data)  # 新代码
    ...
```

### 测试修复 (test_l4_security.py)

```python
def test_marshal_recursion_limit_constant(self):
    """验证常量存在"""
    from velo_loader import MARSHAL_RECURSION_LIMIT
    assert MARSHAL_RECURSION_LIMIT == 1000

def test_safe_marshal_loads_enforces_limit(self):
    """验证函数实现"""
    from velo_loader import safe_marshal_loads
    import sys
    old = sys.getrecursionlimit()
    # 调用后应恢复原限制
    safe_marshal_loads(marshal.dumps(1))
    assert sys.getrecursionlimit() == old

def test_deep_nesting_rejected_with_error(self, tmp_path, velo_binary):
    """验证超限返回错误码 303 (MarshalDepthExceeded)"""
    # 创建 1100 层嵌套 (超过 1000 限制)
    ...
```

---

## 6. 优先级

| 修复项 | 优先级 | 负责 |
|--------|--------|-----|
| 添加 `safe_marshal_loads()` | P0 | Dev |
| 修改 `exec_module()` 调用 | P0 | Dev |
| 添加单元测试 | P0 | QA |
| 添加集成测试 | P1 | QA |

---

## 7. 结论

**当前状态: 安全验收不通过**

在 `safe_marshal_loads()` 实现并经测试验证之前，Phase 5.0 Fast Loader 存在 DoS 风险，不应发布到生产环境。
