"""
Modula Builder - Enhanced Error Handling & Logging System

Provides comprehensive error tracking, logging, and debugging capabilities
"""

import frappe
import traceback
import json
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
import hashlib


class BuilderErrorHandler:
    """Centralized error handling for Modula Builder"""

    ERROR_LEVELS = {
        'DEBUG': 10,
        'INFO': 20,
        'WARNING': 30,
        'ERROR': 40,
        'CRITICAL': 50
    }

    @staticmethod
    def log_error(
        error_type: str,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        level: str = 'ERROR',
        user_id: Optional[str] = None
    ):
        """
        Log an error with full context

        Args:
            error_type: Type of error (e.g., 'JWT_VALIDATION', 'PUBLISH_FAILED')
            message: Human-readable error message
            context: Additional context data
            level: Error level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
            user_id: User who triggered the error
        """
        try:
            error_doc = frappe.get_doc({
                'doctype': 'Builder Error Log',
                'error_type': error_type,
                'error_level': level,
                'message': message,
                'context_json': json.dumps(context or {}),
                'user_id': user_id or frappe.session.user,
                'stack_trace': traceback.format_exc(),
                'request_url': frappe.request.url if frappe.request else None,
                'request_method': frappe.request.method if frappe.request else None,
                'ip_address': frappe.local.request_ip if frappe.local.request_ip else None,
                'user_agent': frappe.request.headers.get('User-Agent') if frappe.request else None
            })
            error_doc.insert(ignore_permissions=True)
            frappe.db.commit()

            # Log to system logs as well
            log_level = BuilderErrorHandler.ERROR_LEVELS.get(level, 40)
            if log_level >= 40:
                frappe.log_error(f"{error_type}: {message}", "Modula Builder Error")

        except Exception as e:
            # Failsafe - if error logging fails, at least log to system
            frappe.log_error(f"Error logging failed: {str(e)}", "Error Logger Error")

    @staticmethod
    def handle_exception(
        exception: Exception,
        error_type: str,
        context: Optional[Dict[str, Any]] = None,
        user_friendly_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Handle an exception and return user-friendly error response

        Returns:
            Dict with error information for API response
        """
        # Log the error
        BuilderErrorHandler.log_error(
            error_type=error_type,
            message=str(exception),
            context=context,
            level='ERROR'
        )

        # Return sanitized error for user
        error_id = hashlib.md5(
            f"{error_type}{datetime.now().isoformat()}".encode()
        ).hexdigest()[:8]

        return {
            'success': False,
            'error': {
                'type': error_type,
                'message': user_friendly_message or "An error occurred. Please try again.",
                'error_id': error_id,
                'timestamp': datetime.now().isoformat()
            }
        }

    @staticmethod
    def get_error_stats(days: int = 7) -> Dict[str, Any]:
        """
        Get error statistics for monitoring

        Args:
            days: Number of days to look back

        Returns:
            Error statistics
        """
        since_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

        stats = frappe.db.sql("""
            SELECT
                error_type,
                error_level,
                COUNT(*) as count,
                MIN(creation) as first_occurrence,
                MAX(creation) as last_occurrence
            FROM `tabBuilder Error Log`
            WHERE creation >= %s
            GROUP BY error_type, error_level
            ORDER BY count DESC
        """, (since_date,), as_dict=True)

        total_errors = sum(s['count'] for s in stats)
        critical_errors = sum(s['count'] for s in stats if s['error_level'] == 'CRITICAL')

        return {
            'total_errors': total_errors,
            'critical_errors': critical_errors,
            'error_breakdown': stats,
            'period_days': days,
            'healthy': critical_errors == 0 and total_errors < 10
        }


class BuilderLogger:
    """Enhanced logging for Modula Builder operations"""

    @staticmethod
    def log_operation(
        operation: str,
        status: str,
        details: Optional[Dict[str, Any]] = None,
        duration_ms: Optional[int] = None
    ):
        """
        Log a builder operation (publish, export, etc.)

        Args:
            operation: Operation name (e.g., 'publish', 'export', 'import')
            status: Status (success, failed, pending)
            details: Operation details
            duration_ms: Operation duration in milliseconds
        """
        try:
            log_doc = frappe.get_doc({
                'doctype': 'Builder Operation Log',
                'operation': operation,
                'status': status,
                'details_json': json.dumps(details or {}),
                'duration_ms': duration_ms,
                'user_id': frappe.session.user
            })
            log_doc.insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            frappe.log_error(f"Operation logging failed: {str(e)}")

    @staticmethod
    def log_api_call(
        endpoint: str,
        method: str,
        status_code: int,
        response_time_ms: int,
        request_data: Optional[Dict] = None,
        response_data: Optional[Dict] = None
    ):
        """Log API call for monitoring and debugging"""
        try:
            frappe.get_doc({
                'doctype': 'Builder API Log',
                'endpoint': endpoint,
                'method': method,
                'status_code': status_code,
                'response_time_ms': response_time_ms,
                'request_json': json.dumps(request_data or {}),
                'response_json': json.dumps(response_data or {}),
                'ip_address': frappe.local.request_ip if frappe.local.request_ip else None
            }).insert(ignore_permissions=True)
            frappe.db.commit()

        except Exception as e:
            frappe.log_error(f"API logging failed: {str(e)}")

    @staticmethod
    def get_performance_metrics(hours: int = 24) -> Dict[str, Any]:
        """
        Get performance metrics for API calls

        Returns:
            Performance statistics
        """
        since_time = (datetime.now() - timedelta(hours=hours)).strftime('%Y-%m-%d %H:%M:%S')

        metrics = frappe.db.sql("""
            SELECT
                endpoint,
                COUNT(*) as total_calls,
                AVG(response_time_ms) as avg_response_time,
                MIN(response_time_ms) as min_response_time,
                MAX(response_time_ms) as max_response_time,
                SUM(CASE WHEN status_code >= 400 THEN 1 ELSE 0 END) as error_count
            FROM `tabBuilder API Log`
            WHERE creation >= %s
            GROUP BY endpoint
            ORDER BY total_calls DESC
        """, (since_time,), as_dict=True)

        return {
            'period_hours': hours,
            'endpoints': metrics,
            'summary': {
                'total_calls': sum(m['total_calls'] for m in metrics),
                'avg_response_time': sum(m['avg_response_time'] for m in metrics) / len(metrics) if metrics else 0,
                'total_errors': sum(m['error_count'] for m in metrics)
            }
        }


# Decorator for automatic error handling
def handle_builder_errors(error_type: str, user_friendly_message: Optional[str] = None):
    """
    Decorator to automatically handle and log errors in API endpoints

    Usage:
        @handle_builder_errors('EXPORT_FAILED', 'Failed to export build')
        def my_api_function():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except Exception as e:
                return BuilderErrorHandler.handle_exception(
                    exception=e,
                    error_type=error_type,
                    context={'function': func.__name__, 'args': str(args)[:200]},
                    user_friendly_message=user_friendly_message
                )
        return wrapper
    return decorator


# Validation helpers
class ValidationError(Exception):
    """Custom validation error"""
    pass


def validate_project_id(project_id: str):
    """Validate project ID format"""
    if not project_id or len(project_id) < 3:
        raise ValidationError("Project ID must be at least 3 characters")

    if not project_id.replace('_', '').replace('-', '').isalnum():
        raise ValidationError("Project ID can only contain letters, numbers, hyphens, and underscores")


def validate_build_code(build_code: str):
    """Validate build code format"""
    if not build_code or not build_code.startswith('b_'):
        raise ValidationError("Build code must start with 'b_'")

    if len(build_code) < 5:
        raise ValidationError("Build code is too short")


def validate_version(version: str):
    """Validate semantic version format"""
    import re
    if not re.match(r'^\d+\.\d+\.\d+$', version):
        raise ValidationError("Version must be in format X.Y.Z (e.g., 1.0.0)")


# Performance monitoring decorator
def monitor_performance(operation_name: str):
    """
    Decorator to monitor function performance

    Usage:
        @monitor_performance('export_build')
        def export_build():
            ...
    """
    def decorator(func):
        def wrapper(*args, **kwargs):
            import time
            start_time = time.time()

            try:
                result = func(*args, **kwargs)
                status = 'success'
                return result
            except Exception as e:
                status = 'failed'
                raise
            finally:
                duration_ms = int((time.time() - start_time) * 1000)
                BuilderLogger.log_operation(
                    operation=operation_name,
                    status=status,
                    details={'function': func.__name__},
                    duration_ms=duration_ms
                )

        return wrapper
    return decorator


# Health check endpoint
@frappe.whitelist(allow_guest=True)
def health_check() -> Dict[str, Any]:
    """
    Health check endpoint for monitoring

    Returns:
        System health status
    """
    try:
        # Check database connection
        frappe.db.sql("SELECT 1")
        db_healthy = True
    except:
        db_healthy = False

    # Check error rates
    error_stats = BuilderErrorHandler.get_error_stats(days=1)

    # Check performance
    perf_metrics = BuilderLogger.get_performance_metrics(hours=1)

    health_status = {
        'status': 'healthy' if db_healthy and error_stats['healthy'] else 'degraded',
        'timestamp': datetime.now().isoformat(),
        'checks': {
            'database': 'ok' if db_healthy else 'failed',
            'error_rate': 'ok' if error_stats['healthy'] else 'high',
            'api_performance': 'ok' if perf_metrics['summary']['avg_response_time'] < 1000 else 'slow'
        },
        'metrics': {
            'errors_last_24h': error_stats['total_errors'],
            'critical_errors': error_stats['critical_errors'],
            'avg_response_time_ms': perf_metrics['summary']['avg_response_time'],
            'total_api_calls_1h': perf_metrics['summary']['total_calls']
        }
    }

    return health_status


# API endpoint for getting error logs (admin only)
@frappe.whitelist()
def get_error_logs(limit: int = 50, error_type: Optional[str] = None) -> Dict[str, Any]:
    """
    Get recent error logs (admin only)

    Args:
        limit: Number of logs to return
        error_type: Filter by error type

    Returns:
        Error logs
    """
    # Check permissions
    if not frappe.has_permission('Builder Settings', 'read'):
        frappe.throw("You do not have permission to view error logs")

    filters = {}
    if error_type:
        filters['error_type'] = error_type

    logs = frappe.get_all(
        'Builder Error Log',
        filters=filters,
        fields=['*'],
        order_by='creation desc',
        limit=limit
    )

    return {
        'logs': logs,
        'count': len(logs),
        'stats': BuilderErrorHandler.get_error_stats()
    }


# Clear old logs (run via scheduler)
def cleanup_old_logs(days: int = 30):
    """
    Clean up old logs to prevent database bloat
    Run this via Frappe scheduler

    Args:
        days: Keep logs newer than this many days
    """
    cutoff_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    # Delete old error logs
    frappe.db.sql("""
        DELETE FROM `tabBuilder Error Log`
        WHERE creation < %s
    """, (cutoff_date,))

    # Delete old operation logs
    frappe.db.sql("""
        DELETE FROM `tabBuilder Operation Log`
        WHERE creation < %s
    """, (cutoff_date,))

    # Delete old API logs (keep shorter - 7 days)
    api_cutoff = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')
    frappe.db.sql("""
        DELETE FROM `tabBuilder API Log`
        WHERE creation < %s
    """, (api_cutoff,))

    frappe.db.commit()

    frappe.logger().info(f"Cleaned up logs older than {days} days")
