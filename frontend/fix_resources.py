
import os

file_path = 'src/pages/Resources.tsx'

with open(file_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Verify the target lines
print(f"Line 409 (Index 408): {lines[408]!r}")
print(f"Line 479 (Index 478): {lines[478]!r}")

# We want to remove lines 409 to 479 (indices 408 to 478 inclusive).
# And replace them with a single line: "        </>\n"

# Check if line 408 starts with comment
if "Global AI Assistant Modal" not in lines[408]:
    print("ERROR: Line 409 does not match expected start of duplicate block.")
    exit(1)

# Check if line 478 ends with /div >
if "</div >" not in lines[478]:
    print("ERROR: Line 479 does not match expected end of duplicate block.")
    exit(1)

# Perform slice
# lines[:408] keeps 0..407 (lines 1..408)
# lines[479:] keeps 479..END (lines 480..END)
new_lines = lines[:408] + ["        </>\n"] + lines[479:]

with open(file_path, 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print("Successfully patched Resources.tsx")
