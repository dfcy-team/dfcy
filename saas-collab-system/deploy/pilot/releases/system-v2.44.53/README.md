# V2.44.53 controlled influencers release

This package records the controlled integration and deployment of Developer B
PR #63 through integration PR #67. The deployed commit is
`37eaa4a3344be9d3a3c6897e6e4936972a429c40`, tagged
`v2.44.53-deployed`.

The application delta is limited to the influencers module and its tests. It
does not change menus, shared layout, routers, permission catalogs, or database
migrations. The controlled review also fixes the remaining profile-edit lock
order so all affected writes acquire Tenant before Influencer.

Production evidence is stored at
`/home/dfcy01/releases/system-v2.44.53-pr63-20260901`. Backend, Celery,
Celery Beat and frontend run V2.44.53. The V2.44.50 custody sidecar and Redis
were not recreated. The release remains pending owner verification.

Rollback uses `rollback-v24453.sh` to restore the V2.44.52 application images.
There is no database rollback because this release applies no migration.
