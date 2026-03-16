def extract_component_styles(page):

    selectors = {
        "navigation": "nav",
        "buttons": "button",
        "links": "a[href]",
        "forms": "form",
        "inputs": "input",
        "selects": "select",
        "textareas": "textarea",
        "headers": "header",
        "footers": "footer",
        "main_content": "main",
        "sidebars": "aside"
    }

    styles = {}

    for component, selector in selectors.items():

        elements = page.locator(selector)
        count = elements.count()

        samples = []

        sample_size = min(count, 5)

        for i in range(sample_size):

            el = elements.nth(i)

            data = el.evaluate(
            """(element) => {

                function normalizeColor(color) {
                    if (!color) return null;

                    if (color.startsWith("rgba")) {
                        const parts = color.replace("rgba(", "").replace(")", "").split(",");
                        return `rgb(${parts[0].trim()}, ${parts[1].trim()}, ${parts[2].trim()})`;
                    }

                    return color;
                }

                function resolveForeground(el) {
                    let current = el;

                    while (current) {
                        const color = window.getComputedStyle(current).color;

                        if (color && !color.includes("rgba(0, 0, 0, 0)") && !color.includes(", 0)")) {
                            return normalizeColor(color);
                        }

                        current = current.parentElement;
                    }

                    return "rgb(0,0,0)";
                }

                function resolveBackground(el) {
                    let current = el;

                    while (current) {
                        const bg = window.getComputedStyle(current).backgroundColor;

                        if (bg && bg !== "rgba(0, 0, 0, 0)" && bg !== "transparent") {
                            return normalizeColor(bg);
                        }

                        current = current.parentElement;
                    }

                    return "rgb(255,255,255)";
                }

                const style = window.getComputedStyle(element);

                return {
                    foreground: resolveForeground(element),
                    background: resolveBackground(element),
                    font_size: style.fontSize
                };

            }"""
            )

            samples.append(data)

        styles[component] = samples

    return styles