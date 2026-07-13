from django.core.management.base import BaseCommand, CommandError

from apps.common.phase3_data_quality import run_phase3_data_quality_checks


class Command(BaseCommand):
    help = "Validate Phase 3 tenant, analytics, alert, lifecycle, sensitivity, and export audit quality."

    def handle(self, *args, **options):
        findings = run_phase3_data_quality_checks()
        if findings:
            self.stderr.write("Phase 3 data quality check failed. Record values are intentionally omitted.")
            for finding in findings:
                self.stderr.write(f"- {finding.check}: count={finding.count}; {finding.detail}")
            raise CommandError(f"Phase 3 data quality found {sum(item.count for item in findings)} issue(s).")
        self.stdout.write(self.style.SUCCESS("Phase 3 data quality checks passed."))
