"""
Modula Builder - Asset Optimizer

Optimizes HTML/CSS/JS artifacts for production:
- HTML minification
- CSS minification and critical CSS extraction
- JS minification
- Image optimization
- Lazy loading
- Resource hints
"""

import frappe
import re
import json
from typing import Dict, Any, List, Optional
from pathlib import Path
import hashlib


class AssetOptimizer:
    """Optimize assets for production"""

    @staticmethod
    def optimize_html(html: str, options: Optional[Dict[str, Any]] = None) -> str:
        """
        Optimize HTML for production

        Args:
            html: HTML content
            options: Optimization options

        Returns:
            Optimized HTML
        """
        options = options or {}

        # Minify if requested
        if options.get('minify', False):
            html = AssetOptimizer._minify_html(html)

        # Extract and inline critical CSS
        if options.get('inline_critical_css', True):
            html = AssetOptimizer._inline_critical_css(html)

        # Add lazy loading to images
        if options.get('lazy_load_images', True):
            html = AssetOptimizer._add_lazy_loading(html)

        # Add resource hints
        if options.get('add_resource_hints', True):
            html = AssetOptimizer._add_resource_hints(html)

        # Optimize inline styles
        if options.get('optimize_inline_styles', True):
            html = AssetOptimizer._optimize_inline_styles(html)

        return html

    @staticmethod
    def _minify_html(html: str) -> str:
        """
        Minify HTML

        Args:
            html: HTML to minify

        Returns:
            Minified HTML
        """
        # Remove comments (but keep conditional comments for IE)
        html = re.sub(r'<!--(?!\[if).*?-->', '', html, flags=re.DOTALL)

        # Remove unnecessary whitespace between tags
        html = re.sub(r'>\s+<', '><', html)

        # Remove leading/trailing whitespace on lines
        html = re.sub(r'^\s+', '', html, flags=re.MULTILINE)
        html = re.sub(r'\s+$', '', html, flags=re.MULTILINE)

        # Collapse multiple spaces into one
        html = re.sub(r'\s{2,}', ' ', html)

        return html.strip()

    @staticmethod
    def _inline_critical_css(html: str) -> str:
        """
        Extract and inline critical CSS

        Args:
            html: HTML content

        Returns:
            HTML with inlined critical CSS
        """
        # Find all <style> tags
        style_pattern = r'<style[^>]*>(.*?)</style>'
        styles = re.findall(style_pattern, html, flags=re.DOTALL)

        if not styles:
            return html

        # Extract critical CSS (above-the-fold styles)
        critical_css = []

        for style_content in styles:
            # Extract rules that apply to common above-the-fold elements
            critical_selectors = [
                r'body\s*\{[^}]+\}',
                r'\.header\s*\{[^}]+\}',
                r'\.nav\s*\{[^}]+\}',
                r'\.hero\s*\{[^}]+\}',
                r'\.container\s*\{[^}]+\}',
                r'h[1-6]\s*\{[^}]+\}',
                r'\.btn\s*\{[^}]+\}',
            ]

            for pattern in critical_selectors:
                matches = re.findall(pattern, style_content)
                critical_css.extend(matches)

        if critical_css:
            # Create inline critical CSS
            critical_style = f'<style>{AssetOptimizer._minify_css("".join(critical_css))}</style>'

            # Add to <head> if it exists
            if '<head>' in html:
                html = html.replace('<head>', f'<head>\n{critical_style}', 1)
            else:
                # Add at beginning
                html = critical_style + html

        return html

    @staticmethod
    def _minify_css(css: str) -> str:
        """
        Minify CSS

        Args:
            css: CSS to minify

        Returns:
            Minified CSS
        """
        # Remove comments
        css = re.sub(r'/\*.*?\*/', '', css, flags=re.DOTALL)

        # Remove whitespace around { } : ;
        css = re.sub(r'\s*([{}:;,])\s*', r'\1', css)

        # Remove unnecessary semicolons
        css = re.sub(r';\s*}', '}', css)

        # Collapse whitespace
        css = re.sub(r'\s+', ' ', css)

        return css.strip()

    @staticmethod
    def _add_lazy_loading(html: str) -> str:
        """
        Add lazy loading to images

        Args:
            html: HTML content

        Returns:
            HTML with lazy loading
        """
        # Add loading="lazy" to img tags that don't have it
        def add_lazy(match):
            tag = match.group(0)
            if 'loading=' not in tag:
                # Insert before closing >
                tag = tag[:-1] + ' loading="lazy">'
            return tag

        html = re.sub(r'<img[^>]+>', add_lazy, html)

        return html

    @staticmethod
    def _add_resource_hints(html: str) -> str:
        """
        Add resource hints for better performance

        Args:
            html: HTML content

        Returns:
            HTML with resource hints
        """
        # Extract external resources
        urls = set()

        # Find stylesheet links
        urls.update(re.findall(r'<link[^>]+href=["\']([^"\']+)["\'][^>]*>', html))

        # Find script sources
        urls.update(re.findall(r'<script[^>]+src=["\']([^"\']+)["\'][^>]*>', html))

        # Find images
        urls.update(re.findall(r'<img[^>]+src=["\']([^"\']+)["\'][^>]*>', html))

        # Filter for external URLs only
        external_urls = [url for url in urls if url.startswith('http')]

        if not external_urls:
            return html

        # Create preconnect hints for unique domains
        domains = set()
        for url in external_urls:
            match = re.match(r'https?://([^/]+)', url)
            if match:
                domains.add(match.group(1))

        hints = []
        for domain in list(domains)[:5]:  # Limit to 5 domains
            hints.append(f'<link rel="preconnect" href="https://{domain}">')

        if hints and '<head>' in html:
            hints_html = '\n'.join(hints)
            html = html.replace('<head>', f'<head>\n{hints_html}', 1)

        return html

    @staticmethod
    def _optimize_inline_styles(html: str) -> str:
        """
        Optimize inline style attributes

        Args:
            html: HTML content

        Returns:
            HTML with optimized inline styles
        """
        def optimize_style_attr(match):
            tag = match.group(0)
            style_match = re.search(r'style=["\']([^"\']+)["\']', tag)

            if style_match:
                style = style_match.group(1)
                # Minify inline style
                style = re.sub(r'\s*:\s*', ':', style)
                style = re.sub(r'\s*;\s*', ';', style)
                style = style.strip()

                # Replace in tag
                tag = tag.replace(style_match.group(1), style)

            return tag

        html = re.sub(r'<[^>]+style=[^>]+>', optimize_style_attr, html)

        return html

    @staticmethod
    def calculate_content_hash(content: str) -> str:
        """
        Calculate hash for content versioning

        Args:
            content: Content to hash

        Returns:
            Content hash (first 8 chars of SHA-256)
        """
        return hashlib.sha256(content.encode()).hexdigest()[:8]

    @staticmethod
    def add_version_hash(url: str, content: str) -> str:
        """
        Add version hash to URL for cache busting

        Args:
            url: Original URL
            content: Content to hash

        Returns:
            URL with version parameter
        """
        hash_value = AssetOptimizer.calculate_content_hash(content)
        separator = '&' if '?' in url else '?'
        return f"{url}{separator}v={hash_value}"


class ImageOptimizer:
    """Image optimization utilities"""

    @staticmethod
    def get_responsive_image_html(
        src: str,
        alt: str,
        sizes: Optional[List[int]] = None
    ) -> str:
        """
        Generate responsive image HTML with srcset

        Args:
            src: Image source URL
            alt: Alt text
            sizes: List of sizes for srcset

        Returns:
            HTML for responsive image
        """
        sizes = sizes or [320, 640, 768, 1024, 1280]

        # Generate srcset (assuming image server supports resizing)
        srcset_parts = []
        for size in sizes:
            # Append size parameter to URL
            separator = '&' if '?' in src else '?'
            sized_url = f"{src}{separator}w={size}"
            srcset_parts.append(f"{sized_url} {size}w")

        srcset = ', '.join(srcset_parts)

        return f'<img src="{src}" srcset="{srcset}" sizes="(max-width: 768px) 100vw, 768px" alt="{alt}" loading="lazy">'

    @staticmethod
    def should_optimize_image(file_path: str) -> bool:
        """Check if image should be optimized"""
        optimizable_extensions = ['.jpg', '.jpeg', '.png', '.gif']
        return any(file_path.lower().endswith(ext) for ext in optimizable_extensions)


class AssetBundler:
    """Bundle and combine assets"""

    @staticmethod
    def bundle_css(css_list: List[str]) -> str:
        """
        Combine and minify multiple CSS files

        Args:
            css_list: List of CSS content strings

        Returns:
            Bundled and minified CSS
        """
        combined = '\n'.join(css_list)
        return AssetOptimizer._minify_css(combined)

    @staticmethod
    def bundle_js(js_list: List[str]) -> str:
        """
        Combine multiple JS files

        Args:
            js_list: List of JS content strings

        Returns:
            Bundled JS
        """
        # Simple concatenation with semicolons for safety
        return ';\n'.join(js_list) + ';'


# API endpoints

@frappe.whitelist()
def optimize_artifact(project_id: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Optimize an artifact

    Args:
        project_id: Project ID
        options: Optimization options

    Returns:
        Optimization result
    """
    if not frappe.has_permission('Builder Page', 'write'):
        frappe.throw("You do not have permission to optimize artifacts")

    # Parse options
    if isinstance(options, str):
        options = json.loads(options)
    options = options or {}

    # Get artifact
    artifact = frappe.db.get_value(
        'Modula Builder Artifact',
        {'project_id': project_id},
        ['html_fragment', 'name'],
        as_dict=True
    )

    if not artifact:
        return {'success': False, 'error': 'Artifact not found'}

    # Optimize HTML
    original_html = artifact.html_fragment
    optimized_html = AssetOptimizer.optimize_html(original_html, options)

    # Calculate savings
    original_size = len(original_html.encode('utf-8'))
    optimized_size = len(optimized_html.encode('utf-8'))
    savings_percent = round((1 - optimized_size / original_size) * 100, 2)

    # Update artifact with optimized version
    frappe.db.set_value(
        'Modula Builder Artifact',
        artifact.name,
        'html_fragment',
        optimized_html
    )

    return {
        'success': True,
        'original_size': original_size,
        'optimized_size': optimized_size,
        'savings_bytes': original_size - optimized_size,
        'savings_percent': savings_percent
    }


@frappe.whitelist()
def get_optimization_suggestions(project_id: str) -> Dict[str, Any]:
    """
    Get optimization suggestions for an artifact

    Args:
        project_id: Project ID

    Returns:
        List of suggestions
    """
    artifact = frappe.db.get_value(
        'Modula Builder Artifact',
        {'project_id': project_id},
        ['html_fragment'],
        as_dict=True
    )

    if not artifact:
        return {'success': False, 'error': 'Artifact not found'}

    html = artifact.html_fragment
    suggestions = []

    # Check for large inline styles
    inline_styles = re.findall(r'style=["\']([^"\']+)["\']', html)
    total_inline_style_size = sum(len(s) for s in inline_styles)

    if total_inline_style_size > 5000:
        suggestions.append({
            'type': 'warning',
            'category': 'CSS',
            'message': f'Large inline styles detected ({total_inline_style_size} bytes). Consider extracting to separate stylesheet.',
            'impact': 'medium'
        })

    # Check for unoptimized images
    img_tags = re.findall(r'<img[^>]+>', html)
    images_without_lazy = [img for img in img_tags if 'loading=' not in img]

    if images_without_lazy:
        suggestions.append({
            'type': 'info',
            'category': 'Images',
            'message': f'{len(images_without_lazy)} images without lazy loading. Enable lazy loading to improve performance.',
            'impact': 'high'
        })

    # Check for missing alt tags
    images_without_alt = [img for img in img_tags if 'alt=' not in img]

    if images_without_alt:
        suggestions.append({
            'type': 'warning',
            'category': 'Accessibility',
            'message': f'{len(images_without_alt)} images missing alt tags. Add alt text for better accessibility and SEO.',
            'impact': 'medium'
        })

    # Check HTML size
    html_size = len(html.encode('utf-8'))

    if html_size > 100000:  # 100KB
        suggestions.append({
            'type': 'warning',
            'category': 'Performance',
            'message': f'Large HTML size ({html_size} bytes). Consider enabling minification.',
            'impact': 'medium'
        })

    return {
        'success': True,
        'suggestions': suggestions,
        'total_suggestions': len(suggestions),
        'html_size': html_size
    }
