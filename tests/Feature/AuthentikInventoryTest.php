<?php

namespace Tests\Feature;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class AuthentikInventoryTest extends TestCase
{
    use RefreshDatabase;

    public function test_inventory_lists_linked_and_unlinked_portal_accounts_with_only_the_expected_fields(): void
    {
        DB::table('users')->insert([
            ['id' => 2, 'name' => 'Member', 'email' => 'member@example.test', 'authentik_id' => 's-22', 'password' => 'private-hash'],
            ['id' => 3, 'name' => 'Legacy', 'email' => 'legacy@example.test', 'authentik_id' => null, 'password' => 'private-hash'],
        ]);
        $issuer = 'https://auth.example.test/application/o/club/';
        $this->assertSame(0, Artisan::call('authentik:inventory', ['issuer' => $issuer]));
        $this->assertSame([
            'issuer' => $issuer,
            'accounts' => [
                ['portal_user_id' => 2, 'subject' => 's-22', 'email' => 'member@example.test'],
                ['portal_user_id' => 3, 'subject' => null, 'email' => 'legacy@example.test'],
            ],
        ], json_decode(Artisan::output(), true, flags: JSON_THROW_ON_ERROR));
        $this->assertDatabaseCount('users', 2);
    }

    public function test_inventory_rejects_invalid_issuers(): void
    {
        $this->artisan('authentik:inventory', ['issuer' => '/relative'])->assertExitCode(1);
    }
}
