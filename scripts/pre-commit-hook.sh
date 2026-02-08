#!/bin/bash
#
# Pre-commit hook: Enforce IMPLEMENTATION_PLAN.md for code changes
#
# Installation:
#   cp scripts/pre-commit-hook.sh .git/hooks/pre-commit
#   chmod +x .git/hooks/pre-commit
#

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Get list of staged Python files (excluding tests)
STAGED_PY_FILES=$(git diff --cached --name-only --diff-filter=ACM | grep '\.py$' | grep -v 'test_' | grep -v '__pycache__')

# Count lines changed (excluding empty lines and comments)
LINES_CHANGED=0
for file in $STAGED_PY_FILES; do
    if [ -f "$file" ]; then
        # Count added lines (ignore blank lines and pure comment lines)
        ADDED=$(git diff --cached "$file" | grep '^+' | grep -v '^+++' | grep -v '^+\s*$' | grep -v '^+\s*#' | wc -l)
        LINES_CHANGED=$((LINES_CHANGED + ADDED))
    fi
done

# Threshold: More than 20 lines of actual code changes requires a plan
THRESHOLD=20

if [ "$LINES_CHANGED" -gt "$THRESHOLD" ]; then
    echo -e "${YELLOW}================================================${NC}"
    echo -e "${YELLOW}  SIGNIFICANT CODE CHANGES DETECTED${NC}"
    echo -e "${YELLOW}================================================${NC}"
    echo ""
    echo -e "  Lines changed: ${RED}$LINES_CHANGED${NC} (threshold: $THRESHOLD)"
    echo ""
    
    # Check if IMPLEMENTATION_PLAN.md exists and was modified recently
    if [ ! -f "IMPLEMENTATION_PLAN.md" ]; then
        echo -e "${RED}ERROR: IMPLEMENTATION_PLAN.md not found!${NC}"
        echo ""
        echo "Per project guidelines, significant code changes require:"
        echo "  1. Create IMPLEMENTATION_PLAN.md documenting changes"
        echo "  2. Get explicit user/reviewer approval"
        echo "  3. Only then commit the changes"
        echo ""
        echo "To bypass (NOT RECOMMENDED):"
        echo "  git commit --no-verify"
        echo ""
        exit 1
    fi
    
    # Check if IMPLEMENTATION_PLAN.md was modified in this commit
    PLAN_STAGED=$(git diff --cached --name-only | grep 'IMPLEMENTATION_PLAN.md')
    if [ -z "$PLAN_STAGED" ]; then
        echo -e "${YELLOW}WARNING: IMPLEMENTATION_PLAN.md exists but wasn't updated${NC}"
        echo ""
        echo "Consider updating the plan to reflect these changes."
        echo ""
        # Just a warning, not blocking
    else
        echo -e "${GREEN}✓ IMPLEMENTATION_PLAN.md is staged${NC}"
    fi
fi

# Check if README.md or instructions.md should be updated
ROUTES_CHANGED=$(echo "$STAGED_PY_FILES" | grep 'routes\.py$')
UTILS_CHANGED=$(echo "$STAGED_PY_FILES" | grep 'utils\.py$')
SERVICES_CHANGED=$(echo "$STAGED_PY_FILES" | grep 'service\.py$')

if [ -n "$ROUTES_CHANGED" ] || [ -n "$UTILS_CHANGED" ] || [ -n "$SERVICES_CHANGED" ]; then
    README_STAGED=$(git diff --cached --name-only | grep 'README.md')
    INSTRUCTIONS_STAGED=$(git diff --cached --name-only | grep 'instructions.md')
    
    if [ -z "$README_STAGED" ] || [ -z "$INSTRUCTIONS_STAGED" ]; then
        echo -e "${YELLOW}================================================${NC}"
        echo -e "${YELLOW}  DOCUMENTATION UPDATE REMINDER${NC}"
        echo -e "${YELLOW}================================================${NC}"
        echo ""
        echo "You modified routes/utils/services but may have forgotten to update:"
        if [ -z "$README_STAGED" ]; then
            echo -e "  - ${YELLOW}README.md${NC}"
        fi
        if [ -z "$INSTRUCTIONS_STAGED" ]; then
            echo -e "  - ${YELLOW}.agent/instructions.md${NC}"
        fi
        echo ""
        echo "This is just a reminder - commit will proceed."
        echo ""
    fi
fi

echo -e "${GREEN}✓ Pre-commit checks passed${NC}"
exit 0
