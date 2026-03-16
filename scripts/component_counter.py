def count_components(page):

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

    component_counts = {}

    for component, selector in selectors.items():

        count = page.locator(selector).count()

        component_counts[component] = count

    return component_counts