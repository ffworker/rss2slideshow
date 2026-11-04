# Custom branding

The default theme is neutral RSS2Slideshow by Bytegeist. Customer/user styling stays local; do not edit tracked application files to customize the screen.

Create an untracked `branding/brand.yaml`:

```yaml
brand_name: "Community News"
tagline: ""
layout: featured
font_family: sans
accent_color: "#2563eb"
background_color: "#f8fafc"
text_color: "#1f2937"
header_color: "#ffffff"
footer_color: "#eef2f7"
logo_mode: normal
source_in_header: false
show_group_logo: false
footer_names: []
```

Add an optional `branding/logo.png` or `branding/logo.svg`. The directory is Git-ignored and mounted read-only inside the Docker container. Layout options for new installations are `standard` and `featured`. The old `bistro` layout identifier is still accepted for compatibility with existing local themes; it renders the featured layout.

The admin editor stores changes separately under `content/ui-settings.yaml`; an uploaded design logo is saved under `content/design-logo.*`. Admin design overrides take precedence over the local branding baseline.

For a consistently branded screen across updates, explicitly set all relevant theme fields in `branding/brand.yaml`. Unspecified values inherit application defaults and may change in newer versions.

## Bistro TV: QR card and article text length

In **/admin → Design-Studio → Layout & Größen**:

- **QR-Code anzeigen**: hides or shows the entire card, including its white
  background and caption. The QR size control scales the card's padding and
  caption in addition to the actual QR pixels.
- **Artikeltext – max. Zeichen**: limits the RSS feed's *summary/description* to
  0–900 characters. Setting 0 hides the description but leaves the headline.
  Longer summaries are shortened with an ellipsis. The original RSS data is
  unchanged; the limit works in normal kiosk mode, TV preview and Anthias
  single-article playlist mode. It cannot display the complete source article
  if the feed does not supply it, and the backend already caps the feed summary
  at 900 characters.
- The length is a ceiling, not a promise that all text will fit on a small
  display: TV text overflow protections may truncate further.

Changes are previewed before saving and persisted into
`content/ui-settings.yaml`. Older designs without these keys continue with
QR visible and up to 900 summary characters.
