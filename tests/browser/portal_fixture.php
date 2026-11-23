<?php

// Run from the paired Laravel checkout. Its guard checks the resolved DB connection
// (and the normal .env database) before a migration or any fixture writes.
use App\Models\Portal\Appointment;
use App\Models\Portal\Committee;
use App\Models\Portal\Membership;
use App\Models\Portal\Organisation;
use App\Models\User;
use App\Services\PortalAccess;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\DB;

$app = require getcwd().'/tests/Support/public-api-bootstrap.php';

if ($argv[1] === 'migrate') {
    exit(Artisan::call('migrate', ['--force' => true, '--no-interaction' => true]));
}

if ($argv[1] !== 'membership') {
    throw new InvalidArgumentException('Expected migrate or membership');
}

// This account must already exist as a result of the real SSO callback.
$manager = User::where('email', $argv[2])->firstOrFail();
$manifest = DB::transaction(function () use ($manager) {
    $suffix = bin2hex(random_bytes(8));
    $association = Organisation::where('slug', 'bulsca')->firstOrFail();
    $createClub = fn ($name) => Organisation::create([
        'name' => $name, 'slug' => strtolower(str_replace(' ', '-', $name)).'-'.$suffix,
        'kind' => 'club', 'parent_id' => $association->id,
    ]);
    $own = $createClub('Browser Club');
    $other = $createClub('Separate Club');
    $membership = Membership::create(['organisation_id' => $own->id, 'user_id' => $manager->id]);
    $committee = Committee::create([
        'organisation_id' => $own->id, 'name' => 'Current committee', 'starts_on' => '2000-01-01',
    ]);
    Appointment::create([
        'organisation_id' => $own->id, 'membership_id' => $membership->id, 'committee_id' => $committee->id,
        'role_id' => app(PortalAccess::class)->managerRole($own)->id,
    ]);
    $member = User::factory()->create(['name' => 'Example Member', 'email' => "member-$suffix@example.test"]);

    return ['own' => $own->id, 'other' => $other->id, 'member' => $member->email];
});
echo json_encode($manifest, JSON_THROW_ON_ERROR);
