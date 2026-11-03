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
