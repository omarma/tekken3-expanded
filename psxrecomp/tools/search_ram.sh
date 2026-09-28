#!/bin/bash
# Search PSX runtime RAM for 4-byte value 0x0000609C (LE: 9c600000)
NC='/c/Program Files (x86)/Nmap/ncat'
TARGET="9c600000"

search_chunk() {
    local addr_hex="$1"
    local addr_dec=$((16#$addr_hex))
    local result
    result=$( (printf '{"cmd":"read_ram","addr":"%s","len":4096}\n' "$addr_hex"; sleep 0.5) | "$NC" localhost 4370 2>/dev/null )

    # Extract hex field using python
    local hexdata
    hexdata=$(echo "$result" | python3 -c "import sys,json; print(json.load(sys.stdin).get('hex',''))" 2>/dev/null)

    if [ -z "$hexdata" ]; then
        return
    fi

    local lower_hex
    lower_hex=$(echo "$hexdata" | tr 'A-F' 'a-f')

    # Search for all occurrences
    local pos=0
    local len=${#lower_hex}
    while [ $pos -lt $len ]; do
        local remaining="${lower_hex:$pos}"
        # Find target in remaining string
        local before="${remaining%%$TARGET*}"
        if [ "$before" = "$remaining" ]; then
            break  # not found
        fi
        local char_offset=${#before}
        # Check byte alignment (must be at even position)
        if [ $(( (pos + char_offset) % 2 )) -ne 0 ]; then
            pos=$((pos + char_offset + 1))
            continue
        fi
        local byte_offset=$(( (pos + char_offset) / 2 ))
        local ram_addr=$((addr_dec + byte_offset))
        printf "  FOUND at 0x%08X (chunk 0x%05X, offset 0x%03X)\n" "$ram_addr" "$addr_dec" "$byte_offset"
        pos=$((pos + char_offset + ${#TARGET}))
    done
}

echo "Searching for $TARGET in kernel range 0x0000-0x8000..."
for addr in 0000 1000 2000 3000 4000 5000 6000 7000; do
    search_chunk "$addr"
done

echo "Searching for $TARGET in shell data range 0x30000-0x90000..."
for i in $(seq 0x30 0x8F); do
    addr=$(printf "%X000" "$i")
    search_chunk "$addr"
done

echo "=== Search complete ==="
