<?php

use Illuminate\Foundation\Inspiring;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Symfony\Component\Console\Output\OutputInterface;

Artisan::command('inspire', function () {
    $this->comment(Inspiring::quote());
})->purpose('Display an inspiring quote');

Artisan::command('authentik:inventory {issuer : Historical Authentik application issuer URL}', function (string $issuer) {
    $url = parse_url($issuer);

    if (! filter_var($issuer, FILTER_VALIDATE_URL) || ! in_array($url['scheme'] ?? '', ['https', 'http'], true)
        || isset($url['user']) || isset($url['pass']) || isset($url['query']) || isset($url['fragment'])) {
        $this->error('Supply the historical Authentik issuer URL, including its application path.');

        return 1;
    }

    $accounts = DB::table('users')->orderBy('id')
        ->get(['id as portal_user_id', 'authentik_id as subject', 'email']);
    $this->output->writeln(
        json_encode(['issuer' => $issuer, 'accounts' => $accounts], JSON_THROW_ON_ERROR | JSON_UNESCAPED_SLASHES),
        OutputInterface::OUTPUT_RAW,
    );

    return 0;
})->purpose('Export legacy portal account identifiers for operator reconciliation (read-only)');
