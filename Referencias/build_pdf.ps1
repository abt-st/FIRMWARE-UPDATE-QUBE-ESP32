param(
  [string]$InputFile = "INVESTIGACION_ARQUITECTURA_MODERNIZACION_QUBE.md",
  [string]$OutputFile = "Investigacion_QUBE_Servo_Emulacion_ESP32_v2.pdf"
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Get-PythonPath {
  $preferred = "C:\Program Files\ANSYS Inc\ANSYS Student\v271\commonfiles\CPython\3_10\winx64\Release\python\python.exe"
  if (Test-Path $preferred) {
    return $preferred
  }

  $candidates = @("python", "py")
  foreach ($candidate in $candidates) {
    try {
      & $candidate --version *> $null
      if ($LASTEXITCODE -eq 0) {
        return $candidate
      }
    } catch {
    }
  }

  throw "No Python interpreter found."
}

$python = Get-PythonPath

if (-not (Test-Path $InputFile)) {
  throw "Input file not found: $InputFile"
}

Write-Host "Using Python:" $python
Write-Host "Input:" $InputFile
Write-Host "Requested output:" $OutputFile

& $python -m pip show pypandoc-binary *> $null
if ($LASTEXITCODE -ne 0) {
  Write-Host "Installing pypandoc-binary..."
  & $python -m pip install pypandoc-binary
  if ($LASTEXITCODE -ne 0) {
    throw "Failed to install pypandoc-binary."
  }
}

$finalOutput = $OutputFile
if (Test-Path $finalOutput) {
  try {
    Remove-Item $finalOutput -Force
  } catch {
    $stem = [System.IO.Path]::GetFileNameWithoutExtension($OutputFile)
    $ext = [System.IO.Path]::GetExtension($OutputFile)
    $stamp = Get-Date -Format "yyyyMMdd_HHmmss"
    $finalOutput = "${stem}_${stamp}${ext}"
    Write-Host "Output file was locked. Using:" $finalOutput
  }
}

$runner = Join-Path $env:TEMP "build_pdf_runner.py"
$code = @'
import sys
import pypandoc

inp = sys.argv[1]
out = sys.argv[2]

try:
    pypandoc.convert_file(inp, "pdf", outputfile=out, extra_args=["--pdf-engine=xelatex", "--quiet"])
except RuntimeError:
    pypandoc.convert_file(
        inp,
        "pdf",
        outputfile=out,
        extra_args=["--pdf-engine=xelatex", "-V", "mainfont=DejaVu Serif", "--quiet"],
    )

print(out)
'@

Set-Content -Path $runner -Value $code -Encoding ASCII

try {
  $outputPath = & $python $runner $InputFile $finalOutput
  if ($LASTEXITCODE -ne 0) {
    throw "PDF compilation failed."
  }

  if (-not (Test-Path $finalOutput)) {
    throw "Compilation finished but output file was not created."
  }

  $f = Get-Item $finalOutput
  Write-Host "PDF generated:" $f.FullName
  Write-Host "Size bytes:" $f.Length
  Write-Host "LastWriteTime:" $f.LastWriteTime
} finally {
  if (Test-Path $runner) {
    Remove-Item $runner -Force
  }
}
