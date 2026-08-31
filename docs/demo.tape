Output assets/demo.gif
Set FontSize 15
Set Width 1100
Set Height 580
Set Padding 20
Set Theme Dracula

# Render a single user message through a model's chat template.
Type "templ8c render --model glm-5.3-flash --message weather"
Enter
Sleep 1500ms

# Run a conformance check (PASS/FAIL + structured diff table).
Type "templ8c check --model glm-5.3-flash"
Enter
Sleep 2500ms

# Check another CN model family.
Type "templ8c check --model qwen3.8"
Enter
Sleep 2500ms

# List supported model families.
Type "templ8c models"
Enter
Sleep 1500ms
