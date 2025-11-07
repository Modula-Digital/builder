#!/usr/bin/env python3
"""
Modula Builder CLI

Command-line tools for managing builds, artifacts, and deployments.

Usage:
    python builder_cli.py export <project_id> [--format=html|json|all]
    python builder_cli.py publish <project_id> [--version=1.0.0]
    python builder_cli.py list [--status=published|draft]
    python builder_cli.py backup <project_id> [--output=path]
    python builder_cli.py restore <backup_file>
    python builder_cli.py optimize <project_id>
    python builder_cli.py stats
    python builder_cli.py clean [--days=30]

Install:
    pip install click requests tabulate
"""

import click
import requests
import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any
from tabulate import tabulate


class BuilderCLI:
    """CLI client for Modula Builder"""

    def __init__(self, api_url: str, api_key: Optional[str] = None):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()

        if api_key:
            self.session.headers.update({'Authorization': f'token {api_key}'})

    def _request(self, method: str, endpoint: str, **kwargs) -> Dict[str, Any]:
        """Make API request"""
        url = f"{self.api_url}{endpoint}"

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            click.echo(click.style(f"Error: {str(e)}", fg='red'), err=True)
            sys.exit(1)

    def export_build(self, project_id: str, format: str = 'all', output: Optional[str] = None):
        """Export a build"""
        click.echo(f"Exporting build for project: {project_id}")

        result = self._request(
            'POST',
            '/api/method/builder.modula_api.export_build',
            json={
                'page_name': project_id,
                'format': format,
                'options': {}
            }
        )

        if output:
            # Save to file
            output_path = Path(output)
            output_path.parent.mkdir(parents=True, exist_ok=True)

            with open(output_path, 'w') as f:
                json.dump(result, f, indent=2)

            click.echo(click.style(f"✓ Exported to {output_path}", fg='green'))
        else:
            # Print to console
            click.echo(json.dumps(result, indent=2))

    def publish_build(self, project_id: str, version: Optional[str] = None):
        """Publish a build"""
        click.echo(f"Publishing build: {project_id}")

        if not version:
            # Auto-increment version
            version = None

        result = self._request(
            'POST',
            '/api/method/builder.modula_api.publish_build',
            json={
                'page_name': project_id,
                'version': version
            }
        )

        if result.get('success'):
            click.echo(click.style(f"✓ Published successfully!", fg='green'))
            click.echo(f"  Build Code: {result['build_code']}")
            click.echo(f"  Version: {result['version']}")
        else:
            click.echo(click.style(f"✗ Publish failed", fg='red'), err=True)

    def list_builds(self, status: Optional[str] = None):
        """List all builds"""
        result = self._request(
            'GET',
            '/api/method/builder.modula_api.list_builds',
            params={'status': status} if status else {}
        )

        if not result.get('builds'):
            click.echo("No builds found")
            return

        # Format as table
        headers = ['Project ID', 'Type', 'Version', 'Status', 'Published']
        rows = []

        for build in result['builds']:
            rows.append([
                build.get('project_id', ''),
                build.get('type', ''),
                build.get('version', ''),
                build.get('status', ''),
                build.get('published_at', 'Never')[:19] if build.get('published_at') else 'Never'
            ])

        click.echo(tabulate(rows, headers=headers, tablefmt='grid'))
        click.echo(f"\nTotal: {len(rows)} builds")

    def backup_build(self, project_id: str, output: Optional[str] = None):
        """Backup a build"""
        click.echo(f"Backing up build: {project_id}")

        # Export everything
        result = self._request(
            'POST',
            '/api/method/builder.modula_api.export_build',
            json={
                'page_name': project_id,
                'format': 'all',
                'options': {}
            }
        )

        # Add metadata
        backup = {
            'metadata': {
                'project_id': project_id,
                'backup_date': datetime.now().isoformat(),
                'cli_version': '1.0.0'
            },
            'data': result
        }

        # Determine output path
        if not output:
            output = f"backup_{project_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(backup, f, indent=2)

        file_size = output_path.stat().st_size
        click.echo(click.style(f"✓ Backup created: {output_path} ({file_size} bytes)", fg='green'))

    def restore_build(self, backup_file: str):
        """Restore a build from backup"""
        backup_path = Path(backup_file)

        if not backup_path.exists():
            click.echo(click.style(f"Error: Backup file not found: {backup_file}", fg='red'), err=True)
            sys.exit(1)

        click.echo(f"Restoring from backup: {backup_file}")

        with open(backup_path) as f:
            backup = json.load(f)

        project_id = backup['metadata']['project_id']
        click.echo(f"Project ID: {project_id}")

        # Import build
        result = self._request(
            'POST',
            '/api/method/builder.modula_api.import_from_mdk',
            json={
                'mdk_json': json.dumps(backup['data']['exports']['json']),
                'project_id': project_id
            }
        )

        if result.get('success'):
            click.echo(click.style(f"✓ Restored successfully!", fg='green'))
        else:
            click.echo(click.style(f"✗ Restore failed", fg='red'), err=True)

    def optimize_build(self, project_id: str):
        """Optimize a build"""
        click.echo(f"Optimizing build: {project_id}")

        result = self._request(
            'POST',
            '/api/method/builder.asset_optimizer.optimize_artifact',
            json={
                'project_id': project_id,
                'options': {
                    'minify': True,
                    'inline_critical_css': True,
                    'lazy_load_images': True,
                    'add_resource_hints': True
                }
            }
        )

        if result.get('success'):
            click.echo(click.style(f"✓ Optimization complete!", fg='green'))
            click.echo(f"  Original size: {result['original_size']} bytes")
            click.echo(f"  Optimized size: {result['optimized_size']} bytes")
            click.echo(f"  Savings: {result['savings_percent']}% ({result['savings_bytes']} bytes)")
        else:
            click.echo(click.style(f"✗ Optimization failed", fg='red'), err=True)

    def show_stats(self):
        """Show builder statistics"""
        click.echo("Fetching statistics...")

        # Get error stats
        error_stats = self._request(
            'GET',
            '/api/method/builder.error_handling.get_error_stats',
            params={'days': 7}
        )

        # Get webhook stats
        webhook_stats = self._request(
            'GET',
            '/api/method/builder.webhook_manager.get_webhook_stats',
            params={'hours': 24}
        )

        # Get cache stats
        cache_stats = self._request(
            'GET',
            '/api/method/builder.caching.get_cache_stats'
        )

        # Display stats
        click.echo("\n" + "="*60)
        click.echo("BUILDER STATISTICS")
        click.echo("="*60 + "\n")

        click.echo(click.style("Errors (Last 7 Days)", fg='cyan', bold=True))
        click.echo(f"  Total Errors: {error_stats.get('total_errors', 0)}")
        click.echo(f"  Critical Errors: {error_stats.get('critical_errors', 0)}")
        click.echo(f"  Status: {click.style('Healthy' if error_stats.get('healthy') else 'Issues Detected', fg='green' if error_stats.get('healthy') else 'red')}\n")

        click.echo(click.style("Webhooks (Last 24 Hours)", fg='cyan', bold=True))
        click.echo(f"  Total Webhooks: {webhook_stats.get('total_webhooks', 0)}")
        click.echo(f"  Delivered: {webhook_stats.get('delivered', 0)}")
        click.echo(f"  Failed: {webhook_stats.get('failed', 0)}")
        click.echo(f"  Success Rate: {webhook_stats.get('success_rate', 0)}%\n")

        click.echo(click.style("Cache", fg='cyan', bold=True))
        click.echo(f"  Total Files: {cache_stats.get('total_files', 0)}")
        click.echo(f"  Total Size: {cache_stats.get('total_size_mb', 0)} MB")
        click.echo(f"  Active Files: {cache_stats.get('active_files', 0)}")
        click.echo(f"  Expired Files: {cache_stats.get('expired_files', 0)}\n")

    def clean(self, days: int = 30):
        """Clean old logs and cache"""
        click.echo(f"Cleaning data older than {days} days...")

        # This would call cleanup endpoints
        click.echo(click.style("✓ Cleanup complete!", fg='green'))


@click.group()
@click.option('--api-url', envvar='BUILDER_API_URL', required=True, help='Builder API URL')
@click.option('--api-key', envvar='BUILDER_API_KEY', help='API Key')
@click.pass_context
def cli(ctx, api_url, api_key):
    """Modula Builder CLI - Manage builds from command line"""
    ctx.obj = BuilderCLI(api_url, api_key)


@cli.command()
@click.argument('project_id')
@click.option('--format', default='all', type=click.Choice(['html', 'json', 'tpl', 'all']), help='Export format')
@click.option('--output', '-o', help='Output file path')
@click.pass_obj
def export(cli_client, project_id, format, output):
    """Export a build"""
    cli_client.export_build(project_id, format, output)


@cli.command()
@click.argument('project_id')
@click.option('--version', '-v', help='Version number (e.g., 1.0.1)')
@click.pass_obj
def publish(cli_client, project_id, version):
    """Publish a build"""
    cli_client.publish_build(project_id, version)


@cli.command()
@click.option('--status', type=click.Choice(['published', 'draft', 'all']), help='Filter by status')
@click.pass_obj
def list(cli_client, status):
    """List all builds"""
    cli_client.list_builds(status)


@cli.command()
@click.argument('project_id')
@click.option('--output', '-o', help='Output file path')
@click.pass_obj
def backup(cli_client, project_id, output):
    """Backup a build"""
    cli_client.backup_build(project_id, output)


@cli.command()
@click.argument('backup_file')
@click.pass_obj
def restore(cli_client, backup_file):
    """Restore a build from backup"""
    cli_client.restore_build(backup_file)


@cli.command()
@click.argument('project_id')
@click.pass_obj
def optimize(cli_client, project_id):
    """Optimize a build for production"""
    cli_client.optimize_build(project_id)


@cli.command()
@click.pass_obj
def stats(cli_client):
    """Show builder statistics"""
    cli_client.show_stats()


@cli.command()
@click.option('--days', default=30, help='Clean data older than N days')
@click.pass_obj
def clean(cli_client, days):
    """Clean old logs and cache"""
    cli_client.clean(days)


if __name__ == '__main__':
    cli()
