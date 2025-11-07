"""
Modula Builder - Smart Caching System

Implements multi-layer caching for optimal performance:
- Memory cache (Redis)
- File cache
- Database query cache
- CDN integration
"""

import frappe
import hashlib
import json
import time
from datetime import datetime, timedelta
from typing import Any, Optional, Callable
from pathlib import Path
import pickle


class BuilderCache:
    """Smart caching system for Modula Builder"""

    # Cache TTL in seconds
    TTL_ARTIFACT_HTML = 3600  # 1 hour
    TTL_ARTIFACT_JSON = 1800  # 30 minutes
    TTL_VERSION_LIST = 600    # 10 minutes
    TTL_USER_SESSION = 7200   # 2 hours

    @staticmethod
    def get_cache_key(prefix: str, *args) -> str:
        """
        Generate cache key from prefix and arguments

        Args:
            prefix: Cache key prefix (e.g., 'artifact', 'version')
            *args: Arguments to include in key

        Returns:
            Cache key string
        """
        key_data = f"{prefix}:{':'.join(str(arg) for arg in args)}"
        return hashlib.md5(key_data.encode()).hexdigest()

    @staticmethod
    def get(key: str, default: Any = None) -> Any:
        """
        Get value from cache

        Args:
            key: Cache key
            default: Default value if not found

        Returns:
            Cached value or default
        """
        try:
            # Try Redis first (fastest)
            if frappe.cache():
                value = frappe.cache().get(key)
                if value is not None:
                    return pickle.loads(value) if isinstance(value, bytes) else value

            # Fallback to file cache
            cache_file = BuilderCache._get_cache_file_path(key)
            if cache_file.exists():
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)

                # Check expiry
                if cache_data['expires_at'] > time.time():
                    return cache_data['value']
                else:
                    # Expired - delete file
                    cache_file.unlink()

        except Exception as e:
            frappe.log_error(f"Cache get error: {str(e)}", "Cache Error")

        return default

    @staticmethod
    def set(key: str, value: Any, ttl: int = 3600):
        """
        Set value in cache with TTL

        Args:
            key: Cache key
            value: Value to cache
            ttl: Time to live in seconds
        """
        try:
            # Set in Redis
            if frappe.cache():
                frappe.cache().setex(key, ttl, pickle.dumps(value))

            # Also set in file cache (fallback)
            cache_file = BuilderCache._get_cache_file_path(key)
            cache_file.parent.mkdir(parents=True, exist_ok=True)

            cache_data = {
                'value': value,
                'expires_at': time.time() + ttl,
                'created_at': time.time()
            }

            with open(cache_file, 'wb') as f:
                pickle.dump(cache_data, f)

        except Exception as e:
            frappe.log_error(f"Cache set error: {str(e)}", "Cache Error")

    @staticmethod
    def delete(key: str):
        """Delete value from cache"""
        try:
            # Delete from Redis
            if frappe.cache():
                frappe.cache().delete(key)

            # Delete from file cache
            cache_file = BuilderCache._get_cache_file_path(key)
            if cache_file.exists():
                cache_file.unlink()

        except Exception as e:
            frappe.log_error(f"Cache delete error: {str(e)}", "Cache Error")

    @staticmethod
    def clear_pattern(pattern: str):
        """
        Clear all cache keys matching pattern

        Args:
            pattern: Pattern to match (e.g., 'artifact:*')
        """
        try:
            # Clear from Redis
            if frappe.cache():
                keys = frappe.cache().keys(pattern)
                if keys:
                    for key in keys:
                        frappe.cache().delete(key)

            # Clear from file cache
            cache_dir = BuilderCache._get_cache_dir()
            for cache_file in cache_dir.glob('*.cache'):
                # This is a simplification - in production you'd want better pattern matching
                cache_file.unlink()

        except Exception as e:
            frappe.log_error(f"Cache clear error: {str(e)}", "Cache Error")

    @staticmethod
    def _get_cache_dir() -> Path:
        """Get cache directory path"""
        cache_dir = Path(frappe.get_site_path('private', 'builder_cache'))
        cache_dir.mkdir(parents=True, exist_ok=True)
        return cache_dir

    @staticmethod
    def _get_cache_file_path(key: str) -> Path:
        """Get file path for cache key"""
        return BuilderCache._get_cache_dir() / f"{key}.cache"


class ArtifactCache:
    """Specialized caching for artifacts"""

    @staticmethod
    def get_artifact_html(project_id: str) -> Optional[str]:
        """Get cached HTML artifact"""
        key = BuilderCache.get_cache_key('artifact_html', project_id)
        return BuilderCache.get(key)

    @staticmethod
    def set_artifact_html(project_id: str, html: str):
        """Cache HTML artifact"""
        key = BuilderCache.get_cache_key('artifact_html', project_id)
        BuilderCache.set(key, html, BuilderCache.TTL_ARTIFACT_HTML)

    @staticmethod
    def get_artifact_json(project_id: str) -> Optional[dict]:
        """Get cached JSON artifact"""
        key = BuilderCache.get_cache_key('artifact_json', project_id)
        return BuilderCache.get(key)

    @staticmethod
    def set_artifact_json(project_id: str, data: dict):
        """Cache JSON artifact"""
        key = BuilderCache.get_cache_key('artifact_json', project_id)
        BuilderCache.set(key, data, BuilderCache.TTL_ARTIFACT_JSON)

    @staticmethod
    def invalidate_artifact(project_id: str):
        """Invalidate all caches for an artifact"""
        BuilderCache.delete(BuilderCache.get_cache_key('artifact_html', project_id))
        BuilderCache.delete(BuilderCache.get_cache_key('artifact_json', project_id))


# Caching decorator
def cached(ttl: int = 3600, key_prefix: str = 'func'):
    """
    Decorator to cache function results

    Usage:
        @cached(ttl=1800, key_prefix='my_function')
        def my_expensive_function(arg1, arg2):
            ...
    """
    def decorator(func: Callable):
        def wrapper(*args, **kwargs):
            # Generate cache key from function name and arguments
            key_parts = [key_prefix, func.__name__]
            key_parts.extend(str(arg) for arg in args)
            key_parts.extend(f"{k}={v}" for k, v in sorted(kwargs.items()))

            cache_key = BuilderCache.get_cache_key(*key_parts)

            # Try to get from cache
            cached_result = BuilderCache.get(cache_key)
            if cached_result is not None:
                return cached_result

            # Not in cache - execute function
            result = func(*args, **kwargs)

            # Store in cache
            BuilderCache.set(cache_key, result, ttl)

            return result

        return wrapper
    return decorator


class CDNIntegration:
    """CDN integration for artifact distribution"""

    @staticmethod
    def get_cdn_url(artifact_path: str) -> str:
        """
        Get CDN URL for artifact

        Args:
            artifact_path: Local artifact path

        Returns:
            CDN URL or local URL if CDN not configured
        """
        cdn_domain = frappe.conf.get('modula_cdn_domain')

        if cdn_domain:
            # Remove leading slashes and construct CDN URL
            clean_path = artifact_path.lstrip('/')
            return f"https://{cdn_domain}/{clean_path}"

        # Return local URL
        return artifact_path

    @staticmethod
    def purge_cdn_cache(artifact_path: str):
        """
        Purge CDN cache for artifact

        Args:
            artifact_path: Path to purge from CDN
        """
        cdn_purge_url = frappe.conf.get('modula_cdn_purge_url')
        cdn_api_key = frappe.conf.get('modula_cdn_api_key')

        if not cdn_purge_url or not cdn_api_key:
            return

        try:
            import requests

            response = requests.post(
                cdn_purge_url,
                headers={
                    'Authorization': f'Bearer {cdn_api_key}',
                    'Content-Type': 'application/json'
                },
                json={
                    'files': [artifact_path]
                },
                timeout=10
            )

            if response.status_code == 200:
                frappe.logger().info(f"CDN cache purged for {artifact_path}")
            else:
                frappe.log_error(f"CDN purge failed: {response.text}", "CDN Error")

        except Exception as e:
            frappe.log_error(f"CDN purge error: {str(e)}", "CDN Error")


class QueryCache:
    """Intelligent query caching"""

    @staticmethod
    def get_versions(artifact_id: int) -> list:
        """Get cached version list"""
        key = BuilderCache.get_cache_key('versions', artifact_id)
        cached = BuilderCache.get(key)

        if cached:
            return cached

        # Not cached - fetch from database
        versions = frappe.get_all(
            'Modula Builder Version',
            filters={'artifact_id': artifact_id},
            fields=['version', 'created_at', 'created_by'],
            order_by='created_at desc'
        )

        BuilderCache.set(key, versions, BuilderCache.TTL_VERSION_LIST)

        return versions

    @staticmethod
    def invalidate_versions(artifact_id: int):
        """Invalidate version cache"""
        key = BuilderCache.get_cache_key('versions', artifact_id)
        BuilderCache.delete(key)


# Cache warming (run on startup or via scheduler)
def warm_cache():
    """Pre-warm cache with frequently accessed data"""
    try:
        # Cache most recent artifacts
        recent_artifacts = frappe.db.sql("""
            SELECT project_id, html_fragment, mdk_json
            FROM modula_builder_artifacts
            WHERE status = 'published'
            ORDER BY published_at DESC
            LIMIT 50
        """, as_dict=True)

        for artifact in recent_artifacts:
            if artifact.get('html_fragment'):
                ArtifactCache.set_artifact_html(
                    artifact['project_id'],
                    artifact['html_fragment']
                )

            if artifact.get('mdk_json'):
                ArtifactCache.set_artifact_json(
                    artifact['project_id'],
                    json.loads(artifact['mdk_json'])
                )

        frappe.logger().info(f"Cache warmed with {len(recent_artifacts)} artifacts")

    except Exception as e:
        frappe.log_error(f"Cache warming error: {str(e)}", "Cache Error")


# Cache cleanup (run via scheduler)
def cleanup_expired_cache():
    """Clean up expired cache files"""
    try:
        cache_dir = BuilderCache._get_cache_dir()
        deleted_count = 0

        for cache_file in cache_dir.glob('*.cache'):
            try:
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)

                # Check if expired
                if cache_data['expires_at'] < time.time():
                    cache_file.unlink()
                    deleted_count += 1

            except:
                # Corrupted cache file - delete it
                cache_file.unlink()
                deleted_count += 1

        if deleted_count > 0:
            frappe.logger().info(f"Cleaned up {deleted_count} expired cache files")

    except Exception as e:
        frappe.log_error(f"Cache cleanup error: {str(e)}", "Cache Error")


# API endpoints for cache management

@frappe.whitelist()
def clear_artifact_cache(project_id: str) -> dict:
    """
    Clear cache for specific artifact

    Args:
        project_id: Project ID to clear cache for

    Returns:
        Success message
    """
    if not frappe.has_permission('Builder Page', 'write'):
        frappe.throw("You do not have permission to clear cache")

    ArtifactCache.invalidate_artifact(project_id)

    return {
        'success': True,
        'message': f'Cache cleared for project {project_id}'
    }


@frappe.whitelist()
def clear_all_cache() -> dict:
    """
    Clear all builder caches (admin only)

    Returns:
        Success message
    """
    if not frappe.has_permission('Builder Settings', 'write'):
        frappe.throw("You do not have permission to clear all caches")

    BuilderCache.clear_pattern('*')

    return {
        'success': True,
        'message': 'All builder caches cleared'
    }


@frappe.whitelist()
def get_cache_stats() -> dict:
    """
    Get cache statistics

    Returns:
        Cache statistics
    """
    try:
        cache_dir = BuilderCache._get_cache_dir()
        cache_files = list(cache_dir.glob('*.cache'))

        total_size = sum(f.stat().st_size for f in cache_files)
        expired_count = 0

        for cache_file in cache_files:
            try:
                with open(cache_file, 'rb') as f:
                    cache_data = pickle.load(f)
                if cache_data['expires_at'] < time.time():
                    expired_count += 1
            except:
                expired_count += 1

        return {
            'total_files': len(cache_files),
            'total_size_mb': round(total_size / (1024 * 1024), 2),
            'expired_files': expired_count,
            'active_files': len(cache_files) - expired_count
        }

    except Exception as e:
        return {
            'error': str(e)
        }
