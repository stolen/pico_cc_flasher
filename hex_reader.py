from binascii import unhexlify

class HexReader:
    """Streaming intel hex reader"""
    f = None
    addr_upper = 0
    addr = 0
    next_chunk = None

    def __init__(self, path):
        self.f = open(path, 'rb')

    def readinto(self, buffer):
        if not self.f:
            return 0
        offset = self.addr
        while self.addr - offset < len(buffer):
            self.writechunk(buffer, offset)
            #print("filled", self.addr - offset, "of", len(buffer))
        return len(buffer)

    def writechunk(self, buffer, offset):
        bufpos = self.addr - offset
        if not self.next_chunk:
            ac = self.get_chunk()   # addr+chunk
            if ac == None:
                # No data in this chunk
                return False
            elif ac == False:
                # No more data to read
                self.pad_buffer(buffer, bufpos, len(buffer) - bufpos)
                self.addr = offset + len(buffer)
                return False
            elif not ac:
                #print("ac", ac, ac == False)
                raise ValueError
        else:
            ac = self.next_chunk
            self.next_chunk = None
        (caddr, cdata) = ac             # chunk address + chunk data
        if caddr - offset > len(buffer):
            # This chunk is beyond current buffer, will copy it next time
            self.next_chunk = ac
            # Pad the buffer to the end
            self.pad_buffer(buffer, bufpos, len(buffer) - bufpos)
            self.addr = offset + len(buffer)
            return False
        if caddr > self.addr:
            # Pad the gap between prev data and new chunk
            self.pad_buffer(buffer, bufpos, caddr - self.addr)
        for i in range(len(cdata)):
            # Copy the actual chunk data
            bufidx = caddr+i-offset
            if bufidx >= len(buffer):
                # Ooops, the record overflows the buffer
                # Wrap the rest of chunk for the next buffer request
                self.addr = caddr+i
                self.next_chunk = (self.addr, cdata[i:])
                return True
            buffer[bufidx] = cdata[i]
        self.addr = caddr + len(cdata)
        return True

    def get_chunk(self):
        if not self.f:
            # EOF reached. Pad the buffer to the end
            return False
        hc = self.f.readline()          # hex chunk
        #print("hex chunk ", hc, "len", len(hc))
        if len(hc) == 0:
            print("WTF", self.f)
            self.f.close()
            self.f = None
            return False
        return self.parse_hex_chunk(hc)

    def parse_hex_chunk(self, hc):
        if (len(hc) < 13) or (hc[0] != ord(':')):
            return False
        data_len = int(hc[1:3], 16)
        data_addr = int(hc[3:7], 16)
        rec_type = int(hc[7:9], 16)
        #print("type", rec_type, "addr", data_addr, "len", data_len)
        if rec_type == 0:
            # Data record
            #print("   -> data ", data_addr, " -> ", (self.addr_upper << 16) + data_addr)
            return ((self.addr_upper << 16) + data_addr, unhexlify(hc[9:9+data_len*2]))
        elif rec_type == 4:
            # Extended linear address record
            self.addr_upper = int(hc[9:9+data_len*2])
            return None
        elif rec_type == 1:
            # EOF
            self.f.close()
            self.f = None
            return False
        else:
            return None

    def pad_buffer(self, buffer, start, count):
        for i in range(count):
            buffer[start+i] = 0xff
