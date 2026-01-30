import struct
import numpy as np
from PIL import Image
from typing import Tuple

def _enc128(num: int) -> bytearray:
    """
    Encodes a number (up to 32767) into 1 or 2 bytes using the variable-length 
    integer scheme specified in the TI documentation.
    """
    if num >= 0 and num < 128:
        return bytearray([num])
    else:
        return bytearray([(num & 0x7f) | 0x80, num >> 7])

def _parse_enc128(data: bytes, index: int) -> Tuple[int, int]:
    """
    Parses a variable-length integer from the byte stream at the given index.
    Returns a tuple (value, new_index).
    """
    if index >= len(data):
        raise ValueError("Unexpected end of data while parsing length.")

    val = data[index]
    if val & 0x80:
        # 2-byte integer
        if index + 1 >= len(data):
            raise ValueError("Unexpected end of data while parsing length.")
        low = val & 0x7f
        high = data[index + 1]
        return (low | (high << 7)), index + 2
    else:
        # 1-byte integer
        return val, index + 1

def _encode_row(row: np.ndarray, prev_row: np.ndarray) -> bytearray:
    """
    Encodes a single row using the TI Enhanced RLE logic.
    """
    width = len(row)
    compressed = bytearray()

    # Create boolean masks for optimization
    # same_prev: True if pixel is same as in previous row
    if prev_row is None:
        same_prev = np.zeros(width, dtype=bool)
    else:
        same_prev = (row == prev_row)

    # same: True if pixel is same as next pixel (horizontal redundancy)
    # This array has size width - 1 (compare i with i+1)
    if width > 1:
        same = (row[:-1] == row[1:])
        # same_either: True if pixel is same as prev OR same as next
        # We compare same_prev[i] with same[i] for i from 0 to width-2
        same_either = np.logical_or(same_prev[:-1], same)
    else:
        same = np.zeros(0, dtype=bool)
        same_either = np.zeros(0, dtype=bool)

    j = 0
    while j < width:
        # 1. Copy n pixels from previous line
        # Command: 0x00 0x01 [encoded n]
        if same_prev[j]:
            run_len = 1
            while j + run_len < width and same_prev[j + run_len]:
                run_len += 1

            compressed += b'\x00\x01'
            compressed += _enc128(run_len)
            j += run_len

        # 2. Repeat single pixel n times
        # Command: [encoded n] [B G R]
        elif j < width - 1 and same[j]:
            start_j = j
            run_len = 2
            # Count repeated pixels
            while j + run_len < width:
                # Check if row[j+run_len-1] == row[j+run_len]
                # We use the 'same' array which stores comparisons.
                # same[index] is True if row[index] == row[index+1]
                if same[j + run_len - 1]:
                    run_len += 1
                else:
                    break

            # Emit command
            compressed += _enc128(run_len)

            # Emit pixel bytes (B, G, R)
            pixel_bytes = struct.pack('>I', row[j])[1:4]
            compressed += pixel_bytes
            j += run_len

        # 3. Single uncompressed pixel
        # Command: 0x01 [B G R]
        elif j >= width - 2 or same_either[j]:
            compressed += b'\x01'
            pixel_bytes = struct.pack('>I', row[j])[1:4]
            compressed += pixel_bytes
            j += 1

        # 4. Multiple uncompressed pixels
        # Command: 0x00 [encoded n] [B G R ...]
        else:
            start_j = j
            # Find sequence of unique pixels
            pixels = bytearray()
            pixels.extend(struct.pack('>I', row[j])[1:4])
            j += 1

            # Continue while we have space and no horizontal repetition or vertical matching
            while j < width - 1 and not same_either[j]:
                pixels.extend(struct.pack('>I', row[j])[1:4])
                j += 1

            # Add the last pixel of the sequence (if we stopped early due to a repeat)
            # Note: If loop stopped because j reached width-1, we need to add that last pixel too
            # But logic above: "while j < width - 1 ..." stops AT width-2.
            # So we must handle the final pixel.
            if j < width:
                pixels.extend(struct.pack('>I', row[j])[1:4])
                j += 1

            count = len(pixels) // 3
            compressed += b'\x00'
            compressed += _enc128(count)
            compressed += pixels

    # End of Line marker
    compressed += b'\x00\x00'
    return compressed

def _decode_row(payload: bytes, offset: int, prev_row: np.ndarray) -> Tuple[np.ndarray, int]:
    """
    Decodes a single row. 
    Returns (decoded_row_array, new_offset).
    """
    decoded_pixels = []
    while True:
        if offset >= len(payload):
            break
        byte0 = payload[offset]
        offset += 1
        if byte0 == 0x00:
            if offset >= len(payload): break
            byte1 = payload[offset]
            offset += 1
            if byte1 == 0x00:
                # End of Line
                break
            elif byte1 == 0x01:
                # Copy Previous Line OR End of Image
                if offset >= len(payload): break
                byte2 = payload[offset]
                # Check for End of Image marker (0x00 0x01 0x00)
                if byte2 == 0x00:
                    # Rewind offset so caller sees it
                    offset -= 3
                    break
                n, offset = _parse_enc128(payload, offset)
                # Copy n pixels from prev_row
                curr_len = len(decoded_pixels)
                if prev_row is not None:
                    # Ensure we don't go out of bounds
                    copy_end = min(curr_len + n, len(prev_row))
                    decoded_pixels.extend(prev_row[curr_len : copy_end])
                    if copy_end < curr_len + n:
                         decoded_pixels.extend([0] * ((curr_len + n) - copy_end))
                else:
                    decoded_pixels.extend([0] * n)
            else:
                # Literal N Pixels sequence: 0x00 [encoded N] ...
                # 'offset' points to the byte AFTER byte1.
                # byte1 is the start of N, so we use offset - 1.
                n, offset = _parse_enc128(payload, offset - 1)

                if offset + n*3 > len(payload): break
                pixels_data = payload[offset : offset + n*3]
                offset += n*3

                for k in range(n):
                    b = pixels_data[k*3]
                    g = pixels_data[k*3 + 1]
                    r = pixels_data[k*3 + 2]
                    val = (b << 16) | (g << 8) | r
                    decoded_pixels.append(val)

        elif byte0 == 0x01:
            # Single uncompressed pixel
            if offset + 2 >= len(payload): break
            b = payload[offset]
            g = payload[offset + 1]
            r = payload[offset + 2]
            offset += 3
            val = (b << 16) | (g << 8) | r
            decoded_pixels.append(val)

        elif byte0 & 0x80 or byte0 > 1:
            # Repeat Pixel Run: [encoded N] [B G R]
            # Backtrack to read N correctly (byte0 is the first byte of N)
            n, offset = _parse_enc128(payload, offset - 1)

            if offset + 2 >= len(payload): break
            b = payload[offset]
            g = payload[offset + 1]
            r = payload[offset + 2]
            offset += 3
            val = (b << 16) | (g << 8) | r

            decoded_pixels.extend([val] * n)

    return np.array(decoded_pixels, dtype=np.uint32), offset

def enhanced_rle_encode(image: Image.Image) -> bytes:
    """
    Encodes a PIL Image (RGB) into the DLPC900 binary format with Enhanced RLE.
    """
    if image.mode != 'RGB':
        # this can be a bit shady, better just make sure you input an rgb file
        print("Warning: implicitly converted your non-RGB image to RGB.")
        image = image.convert('RGB')

    width, height = image.size
    # Convert to uint32 format 0x00BBGGRR
    arr = np.array(image)
    img_uint32 = (arr[:, :, 2].astype(np.uint32) << 16) | \
                 (arr[:, :, 1].astype(np.uint32) << 8) | \
                 (arr[:, :, 0].astype(np.uint32))

    encoded_data = bytearray()

    # Header placeholder (48 bytes)
    encoded_data += bytearray(48)

    prev_row = None
    for y in range(height):
        row = img_uint32[y]
        encoded_data += _encode_row(row, prev_row)
        prev_row = row

    # End of Image marker
    encoded_data += b'\x00\x01\x00'

    # Padding to 4-byte boundary
    pad_len = (-len(encoded_data)) % 4
    encoded_data += bytearray(pad_len)

    # Fill Header
    encoded_data[0:4] = b'Spld' # i wonder what spld stands for
    struct.pack_into('<H', encoded_data, 4, width)
    struct.pack_into('<H', encoded_data, 6, height)
    struct.pack_into('<I', encoded_data, 8, len(encoded_data) - 48)
    encoded_data[12:20] = b'\xFF' * 8
    encoded_data[20:24] = b'\x00\x00\x00\x00' 
    encoded_data[24] = 0x00
    encoded_data[25] = 0x02 # Enhanced RLE
    encoded_data[26] = 0x01
    # Rest 0

    return bytes(encoded_data)

def enhanced_rle_decode(data: bytes) -> Image.Image:
    """
    Decodes DLPC900 Enhanced RLE byte stream back to a PIL Image.
    """
    if len(data) < 48:
        raise ValueError("Data too short.")

    width = struct.unpack('<H', data[4:6])[0]
    height = struct.unpack('<H', data[6:8])[0]
    payload_size = struct.unpack('<I', data[8:12])[0]

    payload = data[48 : 48 + payload_size]

    decoded_rows = []
    offset = 0
    prev_row = None

    # We know the target width, so we can reconstruct rows accurately
    while offset < len(payload):
        # Check for End of Image marker
        if offset + 2 < len(payload) and payload[offset] == 0x00 and payload[offset+1] == 0x01 and payload[offset+2] == 0x00:
            break

        row, offset = _decode_row(payload, offset, prev_row)

        # Ensure the row matches the header width
        if len(row) < width:
            padded = np.zeros(width, dtype=np.uint32)
            padded[:len(row)] = row
            decoded_rows.append(padded)
        elif len(row) > width:
            decoded_rows.append(row[:width])
        else:
            decoded_rows.append(row)

        prev_row = decoded_rows[-1] # Use padded row for next iteration ref

    # Convert to Image
    img_arr = np.zeros((len(decoded_rows), width, 3), dtype=np.uint8)

    for y, row in enumerate(decoded_rows):
        img_arr[y, :, 0] = (row >> 0) & 0xFF
        img_arr[y, :, 1] = (row >> 8) & 0xFF
        img_arr[y, :, 2] = (row >> 16) & 0xFF

    return Image.fromarray(img_arr, 'RGB')

def compression_round_trip(image: Image.Image):
    """
    Performs encoding and decoding to verify all is ok.
    """
    original_data = image.tobytes()
    original_size = len(original_data)

    print("Encoding image...")
    compressed = enhanced_rle_encode(image)
    compressed_size = len(compressed)

    print("Decoding image...")
    decompressed = enhanced_rle_decode(compressed)
    decompressed_data = decompressed.tobytes()

    if original_data == decompressed_data:
        integrity_check = "PASSED"
    else:
        integrity_check = "FAILED (Data Mismatch)"

    if original_size > 0:
        ratio = compressed_size / original_size
        saved = (1 - ratio) * 100

        print("-" * 40)
        print(f"Dimensions:          {image.size[0]}x{image.size[1]}")
        print(f"Original Size:       {original_size:,} bytes")
        print(f"Compressed Size:     {compressed_size:,} bytes")
        print(f"Compression Ratio:   {ratio:.4f}")
        print(f"Space Saved:         {saved:.2f}%")
        print(f"Integrity Check:     {integrity_check}")
        print("-" * 40)

    # Visual Check
    print("Displaying images...")
    image.show(title="Original Image")
    decompressed.show(title="Decompressed Image")