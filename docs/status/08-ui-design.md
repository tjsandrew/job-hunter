# Workspace visual design

Updated 5 October 2026.

## Direction and implementation

Ink-blue navigation, cobalt actions, cool neutral surfaces, and restrained mint/amber accents. Manrope Variable provides distinctive headings; Inter Variable supports dense controls and reading. Both fonts ship through Fontsource packages and Vite assets, with OFL licenses in their packages. The interface no longer requests Google Fonts at runtime.

App styling lives in apps/web/src/theme.css, imported after the existing layout stylesheet. Resume document typography remains controlled by the document layout settings; app branding does not change the PDF renderer.

Use the established colour roles, 8–16px component radii, consistent spacing, and clear title/body/metadata hierarchy. Avoid adding one-off pale text or tiny labels. Interactive elements have visible keyboard focus; motion respects prefers-reduced-motion. Mobile inputs use 16px text where practical, and job actions remain labelled.

## Guidance consulted

- [Carbon typography strategies](https://www.carbondesignsystem.com/building-blocks/foundations/typography/style-strategies): distinguish expressive headings from productive UI text.
- [Material 3 theming](https://developer.android.com/codelabs/m3-design-theming): coherent semantic colour and typography roles.
- [WCAG contrast minimum](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html): minimum 4.5:1 for normal text.

## Verification

- Production build succeeds; existing 15 frontend tests pass.
- Desktop visual inspection at 1440×1000: Discover, Profile and tracker.
- Mobile inspection at 390×844: Discover and populated Resume Studio; scrollWidth equals viewport width, saved footer stays outside editor scroll content.
- Calculated contrast: body on canvas 14.16:1, secondary text on white 5.75:1, white on cobalt 6.20:1, navigation text on ink 9.51:1, placeholder on white 4.69:1.
- These are selected colour-pair and layout checks, not a full accessibility certification.
- Original user tab and personal data were not edited during this visual pass.
