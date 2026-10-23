param(
    [string]$Query = "Explain Newton's second law.",
    [ValidateRange(1, 10)][int]$Attempts = 2
)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONPATH = '.;prompt-lib'
$env:PYTHONIOENCODING = 'utf-8'
$env:GROQ_MIN_INTERVAL_SECONDS = '0'
$env:GROQ_RESUME_ON_RATE_LIMIT = 'true'
$outputFile = 'newton-qwen-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff') + '.jsonl'
& .\.venv-research\Scripts\python.exe -u -m src.experiment --config experiments/B-qwen-groq.json --task responsegen --query "User: $Query" --output $outputFile --max-attempts $Attempts
exit $LASTEXITCODE
