class Norm_Action(object):
    def __init__(self):

        self.min_type_side = 0 # raw val from nn
        self.max_type_side = 0
        self.min_type_side_range = 0
        self.max_type_side_range = 4

        self.min_size = 1
        self.max_size = 1
        self.min_size_range = 1
        self.max_size_range = 100

        self.min_price = 1
        self.max_price = 1
        self.min_price_range = 1
        self.max_price_range = 100

    def update_type_side(self, new_type_side):
        if new_type_side < self.min_type_side:
            self.min_type_side = new_type_side

        if new_type_side > self.max_type_side:
            self.max_type_side = new_type_side
        return 0

    def update_size(self, new_size):
        if new_size < self.min_size:
            self.min_size = new_size

        if new_size > self.max_size:
            self.max_size = new_size
        return 0

    def update_price(self, new_price):
        if new_price < self.min_price:
            self.min_price = new_price

        if new_price > self.max_price:
            self.max_price = new_price
        return 0

    def norm_val(self, val, min_val, max_val, min_range, max_range):
        if max_val - min_val == 0:
            norm = min_range
        else:
            norm = max_range * (val - min_val) / (max_val - min_val)
        return norm

    def norm_vals(self, nn_out_act):
        type_side = nn_out_act[0][0]
        size = nn_out_act[1][0]
        price = nn_out_act[2][0]
        self.update_type_side(type_side)
        self.update_size(size)
        self.update_price(price)
        type_side = self.norm_val(type_side, self.min_type_side, self.max_type_side, self.min_type_side_range, self.max_type_side_range)
        size = self.norm_val(size, self.min_size, self.max_size, self.min_size_range, self.max_size_range)
        price = self.norm_val(price, self.min_price, self.max_price, self.min_price_range, self.max_price_range)
        return type_side, size, price
