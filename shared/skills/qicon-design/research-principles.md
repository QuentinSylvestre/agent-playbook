# Research and Platform Principles

This appendix anchors the skill in stable design principles and current platform guidance. Refresh platform-specific guidance when web access is available and production/export claims matter.

Last researched for this package: 2026-06-19.

## Durable principles

### 1. Recognition beats decoration

Strong app icons and logo marks must be recognizable quickly. Prioritize a distinctive silhouette, clear metaphor or signature shape, and controlled detail. Apple frames app icons as unique, memorable expressions of purpose and personality that help people recognize the app at a glance.

Source: Apple Human Interface Guidelines — App icons: https://developer.apple.com/design/human-interface-guidelines/app-icons

### 2. Icons are small-form communication

Icons must carry meaning in a small form factor. Google Material guidance emphasizes simple, modern, readable icon forms optimized across sizes and platforms.

Sources:
- Material Design 3 — Icons: https://m3.material.io/styles/icons
- Material Icons guide: https://developers.google.com/fonts/docs/material_icons

### 3. Platform app icons have different constraints from brand marks

A core logo mark can be transparent, flexible, and system-independent. An app icon is a platform object and may need contained framing, specific sizes, or background safety. Windows app icon guidance explicitly treats app icons as shell representations of the app and recommends representing core functionality through a metaphor.

Sources:
- Windows app icon design: https://learn.microsoft.com/en-us/windows/apps/design/iconography/app-icon-design
- Windows icon construction: https://learn.microsoft.com/en-us/windows/apps/design/iconography/app-icon-construction

### 4. Avoid unnecessary typography inside app icons

Do not build app icons around words or letters by default. Letter/monogram marks can work, but they must earn it through distinctiveness or conceptual logic. Windows guidance says typography inside app icons should be avoided unless essential because the app name appears with the icon elsewhere in the OS.

Source: https://learn.microsoft.com/en-us/windows/apps/design/iconography/app-icon-design

### 5. Small-size assets need deliberate simplification

Do not blindly shrink a 1024 px hero icon. Small sizes need fewer shapes, stronger contrast, thicker strokes, and clearer silhouettes. Windows notes common shell/icon sizes including 16, 20, 24, 32, 48, 64, and 256 px contexts.

Source: https://learn.microsoft.com/en-us/windows/apps/design/iconography/app-icon-construction

### 6. Contrast and state recognizability matter even when not running a full accessibility module

This skill does not run a dedicated accessibility workflow, but it should still validate practical recognizability across light/dark/checkerboard backgrounds. WCAG non-text contrast guidance uses a 3:1 target for important graphical information against adjacent colors.

Source: W3C WCAG 2.2 Understanding SC 1.4.11 Non-text Contrast: https://www.w3.org/WAI/WCAG22/Understanding/non-text-contrast.html

### 7. Trends are seasoning, not foundation

Glassmorphism, neon, skeuomorphism, gradients, soft 3D, spatial effects, and brutalist minimalism can be valid rendering choices. They should not replace the underlying identity logic. The durable core is silhouette, metaphor, distinctiveness, contrast, simplification, and consistency.

Apple's recent app icon guidance and WWDC materials emphasize light/dark/tinted/clear appearances and dynamic effects, but these should be treated as platform-specific expression layers rather than the whole identity.

Sources:
- Apple Design: https://developer.apple.com/design/
- Apple WWDC app icon appearances: https://developer.apple.com/videos/play/wwdc2025/220/

## Refresh rules

When web access is available, refresh these before final production recommendations:

- Apple Human Interface Guidelines for app icons and icon appearances.
- Google Material Design icon guidance.
- Microsoft Windows app icon construction/sizes.
- PWA favicon/apple-touch/android icon expectations if targeting web/PWA.
- Any target framework-specific icon packaging conventions if the user explicitly asks for implementation in a separate task.

Do not clutter normal creative critique with citations. Cite when making production/platform claims or when updating the skill's research appendix.
