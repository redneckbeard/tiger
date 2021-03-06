class this.Section extends Backbone.Model
    initialize: ->
        @items = new Items(@get "items")


class this.Sections extends Backbone.Collection
    model: Section

    comparator: (section) ->
        return section.get("ordering")


class this.Item extends Backbone.Model
    initialize: ->
        @extras = new Extras(@get "extras")
        @prices = new Variants(@get "prices")
        @choice_sets = new ChoiceSets(@get "choices")


class this.Items extends Backbone.Collection
    model: Item

    comparator: (item) ->
       return item.get("ordering")


class this.Variant extends Backbone.Model


class this.Variants extends Backbone.Collection
    model: Variant


class this.Extra extends Backbone.Model


class this.Extras extends Backbone.Collection
    model: Extra


class this.ChoiceSet extends Backbone.Model
    initialize: ->
        @choices = new Choices(@get "sidedishes")


class this.ChoiceSets extends Backbone.Collection
    model: ChoiceSet


class this.Choice extends Backbone.Model


class this.Choices extends Backbone.Collection
    model: Choice


class LineItem extends Backbone.Model
    initialize: ->
        section_id = @get "section_id"
        item_id = @get "item_id"
        item = App.sections.get(section_id).items.get(item_id)
        @price = item.prices.get (@get "variant").id
        @item = item
            

class Cart extends Backbone.Collection
    model: LineItem

    initialize: (models, options) ->
        @setOptions (options)

    setOptions: (options) ->
        @subtotal = options.subtotal
        @taxes = options.taxes
        @total_plus_tax = options.total_plus_tax
        @coupon = options.coupon
        @discount = options.discount

    refreshCart: (models, options) ->
        @setOptions options
        @refresh models
