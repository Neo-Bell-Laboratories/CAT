param(
    [Parameter(Mandatory = $false)]
    [string]$Exe = (Join-Path $PSScriptRoot 'cats.exe')
)

$ErrorActionPreference = 'Stop'

function Assert-Exit([string]$Label, [int]$Expected = 0) {
    if ($LASTEXITCODE -ne $Expected) {
        throw "$Label returned exit code $LASTEXITCODE (expected $Expected)"
    }
}

function Get-TreeDigest([string]$Root) {
    $items = Get-ChildItem -LiteralPath $Root -Recurse -File | Sort-Object FullName
    $rows = foreach ($item in $items) {
        $relative = $item.FullName.Substring($Root.Length).TrimStart([char[]]@('\', '/'))
        $hash = (Get-FileHash -LiteralPath $item.FullName -Algorithm SHA256).Hash
        "$relative`t$($item.Length)`t$hash"
    }
    return [string]::Join("`n", $rows)
}

if (-not (Test-Path -LiteralPath $Exe -PathType Leaf)) {
    throw "CAT executable not found: $Exe"
}

& $Exe --version
Assert-Exit 'version'

$work = Join-Path $env:TEMP ("cats-cli-smoke-" + [guid]::NewGuid().ToString('N'))
$source = Join-Path $work 'source tree'
$nested = Join-Path $source 'nested'
New-Item -ItemType Directory -Path $nested -Force | Out-Null
[IO.File]::WriteAllBytes((Join-Path $source 'binary.dat'), [byte[]](0, 1, 2, 127, 128, 254, 255))
[IO.File]::WriteAllBytes((Join-Path $source 'empty.dat'), [byte[]]@())
[IO.File]::WriteAllText((Join-Path $nested 'text file.txt'), "CAT Windows smoke`r`n", [Text.UTF8Encoding]::new($false))
$expected = Get-TreeDigest $source

try {
    $cases = @(
        @{ Name = 'v07'; Flags = @('-e'); Suffix = '.cat'; Decode = @('-d') },
        @{ Name = 'v08'; Flags = @('-e', '-c'); Suffix = '.cat'; Decode = @('-d', '-c') },
        @{ Name = 'gzip-v07'; Flags = @('-e', '-g'); Suffix = '.cat.gz'; Decode = @('-d') },
        @{ Name = 'gzip-v08'; Flags = @('-e', '-c', '-g'); Suffix = '.cat.gz'; Decode = @('-d', '-c') }
    )

    foreach ($case in $cases) {
        $archive = Join-Path $work ($case.Name + $case.Suffix)
        $restored = Join-Path $work ($case.Name + '-restored')
        $encodeArgs = @($case.Flags) + @($source, '--output', $archive)
        & $Exe @encodeArgs
        Assert-Exit "$($case.Name) encode"
        if (-not (Test-Path -LiteralPath $archive -PathType Leaf)) {
            throw "$($case.Name) archive was not created"
        }
        & $Exe -v $archive
        Assert-Exit "$($case.Name) verify"
        $decodeArgs = @($case.Decode) + @($archive, $restored)
        & $Exe @decodeArgs
        Assert-Exit "$($case.Name) decode"
        $actualRoot = Join-Path $restored (Split-Path -Leaf $source)
        if ((Get-TreeDigest $actualRoot) -ne $expected) {
            throw "$($case.Name) restored tree differs from source"
        }
    }

    $existing = Join-Path $work 'existing destination'
    New-Item -ItemType Directory -Path $existing | Out-Null
    $sentinel = Join-Path $existing 'sentinel.txt'
    [IO.File]::WriteAllText($sentinel, 'keep')
    & $Exe -d (Join-Path $work 'v07.cat') $existing 2>$null
    Assert-Exit 'refuse existing destination' 1
    if ([IO.File]::ReadAllText($sentinel) -ne 'keep') {
        throw 'Existing destination contents changed after refused extraction'
    }

    Write-Output 'PASS: Windows CLI encode/decode, v0.7/v0.8, gzip, verify, and no-overwrite checks'
}
finally {
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue
}
