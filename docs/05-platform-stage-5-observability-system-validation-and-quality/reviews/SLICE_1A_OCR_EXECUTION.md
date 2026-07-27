# Stage 5 第一部分 Slice 1A：OCR 执行交接

状态：白名单副本和三块 preview 已完成；等待用户执行真实 OCR

日期：2026-07-27

## 1. 已准备范围

仓库外白名单副本：

```powershell
$env:USERPROFILE\.codex\visualizations\2026\07\27\019fa11a-c1fa-7200-9d10-1f6abe74ad18\stage5_slice1a_ocr
```

副本是独立临时 Git 工作区，不属于产品仓库。六个副本与当前产品源码的 SHA-256
逐文件一致，未包含 `.tmp/`、`artifacts/`、`.env`、provider 配置、上传资料、
日志或 Stage 5 规划文档。

| 分块 | 文件数 | 范围 |
|---|---:|---|
| `01-api-contract` | 3 | router、schema、运行摘要 service |
| `02-api-tests` | 1 | Agent Run HTTP 行为测试 |
| `03-web` | 2 | Web API 类型与运行记录面板 |

Preview 已确认分别发现 3、1、2 个可审文件，没有零文件块。

## 2. 用户执行命令

在产品仓库根目录打开 PowerShell，完整执行下面一段。它会先检查 OCR provider，
随后按顺序运行三块；每块使用单并发和 10 分钟单任务超时，输出分别归档到
Stage 5 `reviews/raw/`。

```powershell
$ocrRoot = Join-Path $env:USERPROFILE '.codex\visualizations\2026\07\27\019fa11a-c1fa-7200-9d10-1f6abe74ad18\stage5_slice1a_ocr'
$rawRoot = Join-Path (Get-Location) 'docs\05-platform-stage-5-observability-system-validation-and-quality\reviews\raw'

if (-not (Test-Path -LiteralPath (Join-Path $ocrRoot '.git'))) {
    throw "OCR 白名单副本不存在或不是独立工作区：$ocrRoot"
}
New-Item -ItemType Directory -Path $rawRoot -Force | Out-Null

ocr llm test
if ($LASTEXITCODE -ne 0) {
    throw "OCR provider 检查失败，已停止。"
}

$blocks = @(
    @{
        Name = '01-api-contract'
        Background = 'Stage 5 Slice 1A safe Agent Run projection. Review workspace isolation, deleted-owner degradation, seven-role filtering, Code Lab language allowlist, and sensitive-field exclusion. No schema, migration, provider, cost, or worker changes are allowed.'
    },
    @{
        Name = '02-api-tests'
        Background = 'Stage 5 Slice 1A HTTP behavior tests. Review whether tests exercise public API and real ORM behavior, cover seven roles, four owner types, unknown values, broken chains, workspace isolation, filters, and forbidden fields without source-inspection shortcuts.'
    },
    @{
        Name = '03-web'
        Background = 'Stage 5 Slice 1A run-history UI. Review safe unknown-role fallback, five identity kinds, seven filters, Code Lab language display, accessible expansion, loading/error/empty states, and responsive behavior. No dashboard, provider, model, or cost UI is in scope.'
    }
)

Push-Location $ocrRoot
try {
    foreach ($block in $blocks) {
        # ocr scan --path is resolved relative to the current OCR workspace.
        # Passing the absolute block path here makes the current OCR CLI
        # silently fall back to the workspace root and discover zero files.
        $path = $block.Name
        $output = Join-Path $rawRoot ($block.Name + '.txt')

        Write-Host "START $($block.Name)"
        ocr scan --audience human --path $path --concurrency 1 --timeout 10 --background $block.Background 2>&1 |
            Tee-Object -FilePath $output
        $exitCode = $LASTEXITCODE

        if ($exitCode -ne 0) {
            throw "OCR 块 $($block.Name) 退出码为 $exitCode，已停止。"
        }

        $text = Get-Content -LiteralPath $output -Raw
        if ($text -match 'No files changed|0 file\(s\)|0 files discovered') {
            throw "OCR 块 $($block.Name) 没有发现文件，已停止。"
        }
        if ($text -match '(?i)timed out|timeout exceeded|budget (exceeded|truncated)') {
            throw "OCR 块 $($block.Name) 出现超时或预算截断，已停止。"
        }

        Write-Host "DONE $($block.Name)"
    }
}
finally {
    Pop-Location
}
```

不要增加 `--max-tokens-budget`，不要把路径改回产品仓库根目录，也不要扫描
`.tmp/` 或 `artifacts/`。

## 3. 执行后

三块都显示 `DONE` 后，回到 Codex 告知“Slice 1A OCR 已执行完成”。Codex 将读取：

```text
reviews/raw/01-api-contract.txt
reviews/raw/02-api-tests.txt
reviews/raw/03-web.txt
```

随后核对每块实际文件数、Summary 和 findings，结合完整仓库上下文分类、修复并
复验。OCR 输出本身不自动构成 Slice 通过结论。
