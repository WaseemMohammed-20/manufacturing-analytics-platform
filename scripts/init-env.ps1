param([switch]$ExistingDatabase)

$ErrorActionPreference = 'Stop'

if (Test-Path .env) {
    throw '.env already exists. Leave it intact and rotate its credentials manually if needed.'
}

function New-Secret {
    param([int]$ByteCount = 48)
    $bytes = New-Object byte[] $ByteCount
    $generator = [Security.Cryptography.RandomNumberGenerator]::Create()
    try {
        $generator.GetBytes($bytes)
    } finally {
        $generator.Dispose()
    }
    [Convert]::ToBase64String($bytes)
}

if ($ExistingDatabase) {
    $securePassword = Read-Host 'Enter the current PostgreSQL password for the existing data volume' -AsSecureString
    $passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
    try {
        $postgresPassword = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    }
    if ([string]::IsNullOrWhiteSpace($postgresPassword)) {
        throw 'The PostgreSQL password cannot be empty.'
    }
} else {
    $postgresPassword = New-Secret
}
$supersetSecret = New-Secret
$adminPassword = New-Secret

@"
POSTGRES_DB=manufacturing
POSTGRES_USER=manufacturing
POSTGRES_PASSWORD=$postgresPassword
SUPERSET_SECRET_KEY=$supersetSecret
SUPERSET_ADMIN_USERNAME=admin
SUPERSET_ADMIN_PASSWORD=$adminPassword
SUPERSET_ADMIN_EMAIL=admin@example.com
"@ | Set-Content -Path .env -Encoding ascii

Write-Output 'Created .env with generated credentials. Values were not printed.'