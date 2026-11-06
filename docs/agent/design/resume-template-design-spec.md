# Resume Template Design Spec

> Swiss International Style specifications for resume templates.

## Typography

| Element | Font | Size | Weight |
|---------|------|------|--------|
| Name | serif | 2xl | bold |
| Title | serif | lg | normal |
| Section heading | serif | lg | semibold |
| Job title | sans | base | semibold |
| Company | sans | sm | medium |
| Body text | sans | sm | normal |
| Metadata | mono | xs | normal |

## Spacing

| Element | Spacing |
|---------|---------|
| Between sections | 16-24px |
| Between items | 8-12px |
| Line height | 1.4-1.6 |

## Colors

```
Text: #000000 (Ink)
Links: #1D4ED8 (Hyper Blue)
Dividers: #E5E5E0
Background: #FFFFFF
```

## Section Order

1. Header (name, title, contact)
2. Summary
3. Work Experience
4. Projects
5. Education (formal branch only; other branch parks it late)
6. Additional — skills only (languages labeled line in modern/latex/clean; swiss-single header grid only)
7. Custom-section cluster, then the render-only late modules Certifications/Training and Awards (independent titled sections; data stays in `additional`, projected after custom sections — never meta rows), then honors / self-evaluation

## Two-Column Layout

```
┌────────────────────┬──────────┐
│     Main (65%)     │ Side 35% │
├────────────────────┼──────────┤
│   Summary          │ Education│
│   Experience       │ Skills   │
│   Projects         │ Languages│
│   Custom Sections  │ Links    │
│   Certifications   │          │
│   Awards           │          │
└────────────────────┴──────────┘
```

## CSS Classes

```css
.resume-section        /* Section wrapper */
.resume-section-title  /* Heading */
.resume-items          /* Item container */
.resume-item           /* Single entry */
```

## Print Considerations

- Never split `.resume-item` across pages
- Never orphan section headers
- Minimum 50% page fill before break
